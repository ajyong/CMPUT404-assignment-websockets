#!/usr/bin/env python
# coding: utf-8
# Copyright (c) 2013-2014 Abram Hindle and Aaron Yong
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import flask
from flask import Flask, request, redirect, url_for, make_response
from flask_sockets import Sockets
import gevent
from gevent import queue
import time
import json
import os

app = Flask(__name__)
sockets = Sockets(app)
app.debug = True

class World:
    def __init__(self):
        self.space = dict()
        # we've got listeners now!
        self.set_listeners = list()
        self.clear_listeners = list()
        
    def add_set_listener(self, listener):
        self.set_listeners.append( listener )

    def add_clear_listener(self, listener):
        self.clear_listeners.append(listener)

    def update(self, entity, key, value):
        entry = self.space.get(entity,dict())
        entry[key] = value
        self.space[entity] = entry
        self.update_set_listeners( entity )

    def set(self, entity, data):
        self.space[entity] = data
        self.update_set_listeners( entity )

    def clear(self):
        self.space = dict()
        self.update_clear_listeners()

    def get(self, entity):
        return self.space.get(entity,dict())
    
    def world(self):
        return self.space

    def update_set_listeners(self, entity):
        '''update the set listeners'''
        for listener in self.set_listeners:
            listener(entity, self.get(entity))

    def update_clear_listeners(self):
        '''update the clear listeners'''
        for listener in self.clear_listeners:
            listener()

myWorld = World()        

class Client:
    def __init__(self):
        self.queue = queue.Queue()

    def put(self, v):
        self.queue.put_nowait(v)

    def get(self):
        return self.queue.get()

clients = list()

def set_listener( entity, data ):
    # For each client, put the entity and its data in the queue
    for client in clients:
        client.put(json.dumps({entity: data}))

def clear_listener():
    # For each client, put the empty world in the queue
    for client in clients:
        client.put(json.dumps(myWorld.world()))

myWorld.add_set_listener( set_listener )
myWorld.add_clear_listener( clear_listener )

# Make a JSON response from raw data
def make_json_response(rawData):
    resp = make_response(json.dumps(rawData))
    resp.headers['Content-Type'] = 'application/json'
    return resp


@app.route('/')
def hello():
    return redirect(url_for('static', filename='index.html'))


def read_ws(ws,client):
    '''A greenlet function that reads from the websocket and updates the world'''
    try:
        while True:
            msg = ws.receive()
            print "WS RECV: %s" % msg
            if (msg is not None):
                packet = json.loads(msg)
                print "Packet: %s" % packet

                for name, data in packet.iteritems():
                    entity = myWorld.get(name)

                    for k, v in data.iteritems():
                        # Do it this way so we don't call the listener until
                        # all KV pairs have been updated
                        entity[k] = v

                    myWorld.set(name, entity)
            else:
                break
    except:
        pass

    return None


@sockets.route('/subscribe')
def subscribe_socket(ws):
    '''Fufill the websocket URL of /subscribe, every update notify the
       websocket and read updates from the websocket '''
    print "A client has subscribed."
    client = Client()
    clients.append(client)

    # Give the new client the current world data
    client.put(json.dumps(myWorld.world()));

    g = gevent.spawn( read_ws, ws, client )
    try:
        while True:
            # Block here until we get something from the client's queue
            msg = client.get()
            print "Got a message:\n%s" % msg
            ws.send(msg)
    except Exception as e:# WebSocketError as e:
        print "WS Error: %s" % e
    finally:
        clients.remove(client)
        gevent.kill(g)


def flask_post_json():
    '''Ah the joys of frameworks! They do so much work for you
       that they get in the way of sane operation!'''
    if (request.json != None):
        return request.json
    elif (request.data != None and request.data != ''):
        return json.loads(request.data)
    else:
        return json.loads(request.form.keys()[0])


@app.route("/entity/<entity>", methods=['POST','PUT'])
def update(entity):
    '''update the entities via this interface'''
    data = flask_post_json(request)

    for key, value in data.iteritems():
        myWorld.update(entity, key, value);

    return make_json_response(myWorld.get(entity))


@app.route("/world", methods=['POST','GET'])    
def world():
    '''Return the world as JSON'''
    return make_json_response(myWorld.world())


@app.route("/entity/<entity>")    
def get_entity(entity):
    '''This is the GET version of the entity interface, return a representation of the entity'''
    return make_json_response(myWorld.get(entity))


@app.route("/clear", methods=['POST','GET'])
def clear():
    myWorld.clear()
    
    return make_json_response(myWorld.world())


if __name__ == "__main__":
    ''' This doesn't work well anymore:
        pip install gunicorn
        and run
        gunicorn -k flask_sockets.worker sockets:app
    '''
    app.run()
