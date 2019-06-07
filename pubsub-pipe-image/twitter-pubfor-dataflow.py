#!/usr/bin/env python
# Copyright 2015 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""This script uses the Twitter Streaming API, via the tweepy library,
to pull in tweets and publish them to a PubSub topic.
"""

import json
import base64
import datetime
from dateutil import parser
import os
from tweepy import OAuthHandler
from tweepy import Stream
from tweepy.streaming import StreamListener

import utils

# Get your twitter credentials from the environment variables.
# These are set in the 'twitter-stream.json' manifest file.
consumer_key = os.environ['CONSUMERKEY']
consumer_secret = os.environ['CONSUMERSECRET']
access_token = os.environ['ACCESSTOKEN']
access_token_secret = os.environ['ACCESSTOKENSEC']

PUBSUB_TOPIC = os.environ['PUBSUB_TOPIC']
NUM_RETRIES = 3


def publish(client, pubsub_topic, data_lines):
    """Publish to the given pubsub topic."""
    messages = []
    for line in data_lines:
        pub = base64.urlsafe_b64encode(line)
        tweet_dict = json.loads(line)
        # input_format = '%a %b %d %H:%M:%S %z %Y'
        dest_format = '%Y-%m-%dT%H:%M:%SZ'
        try:
            pubsub_timestamp = parser.parse(tweet_dict['created_at']).strftime(dest_format)
        except:
            print("Error encountered in parsing a 'created_at' timestamp from:\n{0}".format(tweet_dict))
            continue
        # print("tweet_dict: {0}".format(tweet_dict))
        response = client.publish(topic=pubsub_topic,
                    data=pub, created_at=pubsub_timestamp)
        # messages.append({'data': pub})
    # body = {'messages': messages}
    # resp = client.publish(
    #         topic=pubsub_topic, body=body, created_at= ).execute(num_retries=NUM_RETRIES)
    # return resp


class StdOutListener(StreamListener):
    """A listener handles tweets that are received from the stream.
    This listener dumps the tweets into a PubSub topic
    """

    count = 0
    twstring = ''
    tweets = []
    batch_size = 50
    total_tweets = 10000000
    client = utils.create_pubsub_client(utils.get_credentials())

    def write_to_pubsub(self, tw):
        print('Publishing to topic {}'.format(PUBSUB_TOPIC))
        publish(self.client, PUBSUB_TOPIC, tw)

    def on_data(self, data):
        """What to do when tweet data is received."""
        self.tweets.append(data)
        if len(self.tweets) >= self.batch_size:
            self.write_to_pubsub(self.tweets)
            self.tweets = []
        self.count += 1
        # if we've grabbed more than total_tweets tweets, exit the script.
        # If this script is being run in the context of a kubernetes
        # replicationController, the pod will be restarted fresh when
        # that happens.
        if self.count > self.total_tweets:
            return False
        if (self.count % 1000) == 0:
            print 'count is: %s at %s' % (self.count, datetime.datetime.now())
        return True

    def on_error(self, status):
        print status


if __name__ == '__main__':
    print '....'
    listener = StdOutListener()
    auth = OAuthHandler(consumer_key, consumer_secret)
    auth.set_access_token(access_token, access_token_secret)

    print 'stream mode is: %s' % os.environ['TWSTREAMMODE']

    entities = [
    "NBA finals",
    "NBA",
    "Toronto",
    "Raptors",
    "Nick Nurse",
    "Kawhi Leonard",
    "Kyle Lowry",
    "Jeremy Lin",
    "Fred VanVleet",
    "Marc Gasol",
    "Pascal Siakam",
    "Danny Green",
    "Serge Ibaka",
    "OG Anunoby",
    "Norman Powell",
    "Patrick McCaw"
    "Chris Boucher",
    "Jodie Meeks",
    "Eric Moreland",
    "Malcolm Miller",
    "Jordan Loyd",
    "Golden State",
    "Warriors",
    "Steve Kerr",
    "Kevin Durant",
    "Stephen Curry",
    "DeMarcus Cousins",
    "Klay Thompson",
    "Draymond Green",
    "Andre Iguodala",
    "Andrew Bogut",
    "Damion Lee",
    "Jordan Bell",
    "Shaun Livingston",
    "Kevon Looney",
    "Jonas Jerebko",
    "Quinn Cook",
    "Alfonzo McKinnie",
    "Jacob Evans",
    "Damian Jones",
    "Marcus Derrickson",
    "Nav Bhatia",
    "#DubNation",
    "#WeTheNorth",
    "#Basketball",
    "#Sports",
    "#NBAFinals",
    "#Warriors",
    "#Raptors",
    "#GoldenState",
    "#ESPN",
    "#BBall",
    "#Dunk",
    "#Basket",
    "#StephCurry",
    "#KevinDurant",
    "#NBAbasketball",
    "#GoldenStateWarriors",
    "#Curry",
    "#Hoops",
    "#Player",
    "#Team",
    "#Game",
    "#NBAhistory"
    ]

    stream = Stream(auth, listener)
    # set up the streaming depending upon whether our mode is 'sample', which
    # will sample the twitter public stream. If not 'sample', instead track
    # the given set of keywords.
    # This environment var is set in the 'twitter-stream.yaml' file.
    if os.environ['TWSTREAMMODE'] == 'sample':
        stream.sample()
    else:
        print('starting to filter')
        stream.filter(
                track= entities + [entity.lower() for entity in entities]
                )
