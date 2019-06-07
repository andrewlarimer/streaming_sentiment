from __future__ import division

import os
import json
import logging
from datetime import datetime, timedelta
import dateutil.parser
from dateutil.tz import tzutc

import google.cloud.logging

# Instantiates a client
client = google.cloud.logging.Client()

# Connects the logger to the root logging handler; by default this captures
# all logs at INFO level and higher
client.setup_logging()

import apache_beam as beam
from apache_beam import Pipeline, CombinePerKey, FlatMap, Map, WindowInto, window
from apache_beam.options.pipeline_options import PipelineOptions, StandardOptions, GoogleCloudOptions
from apache_beam.io.gcp.pubsub import ReadFromPubSub
#from apache_beam.io.textio import WriteToText
from apache_beam.io.gcp.bigquery import WriteToBigQuery, BigQuerySource

# Create and set your PipelineOptions.
options = PipelineOptions() #(flags=argv)

# For Cloud execution, set the Cloud Platform project, job_name,
# staging location, temp_location and specify DataflowRunner.
google_cloud_options = options.view_as(GoogleCloudOptions)
google_cloud_options.project = 'got-sentiment'
google_cloud_options.region = 'us-central1'
google_cloud_options.job_name = 'got-senti-job-' + datetime.now().strftime("%H-%M")
google_cloud_options.staging_location = 'gs://springml-got-sentiment/binaries'
google_cloud_options.temp_location = 'gs://springml-got-sentiment/temp'
options.view_as(StandardOptions).runner = 'DataflowRunner'
options.view_as(StandardOptions).streaming = True

# from apache_beam import window
# fixed_windowed_items = (
#     items | 'window' >> beam.WindowInto(window.FixedWindows(60)))

PUBSUB_TOPIC = 'projects/got-sentiment/topics/s08ep06'
BQ_DATASET = 'got_sentiment'
PROJECT_ID = 'got-sentiment'

entity_map = {'tyrion':'Tyrion', 'sansa':'Sansa', 'dany':'Daenerys', 'varys':'Varys',
    'daenerys':'Daenerys','jon':'Jon Snow', 'arya': 'Arya', 'bran':'Bran',
    'grey worm': 'Grey Worm', 'drogon': 'Drogon', 'bronn':'Bronn', 'gendry':'Gendry',
    'brienne':'Brienne', 'tormund':'Tormund', ' sam ':'Sam', 'gilly':'Gilly',
    'the hound':'The Hound', 'cleganebowl':'Cleganebowl', 'clegane bowl':'Cleganebowl',
    'cersei':'Cersei', 'jamie':'Jaime', 'jaime':'Jaime', 'missandei':'Missandei',
    'd&d':'D&D', 'damp;d':'D&D','grrm':'George R.R. Martin', '#got':'Game of Thrones',
    'theon':'Theon', 'davos':'Ser Davos', 'king\'s landing':'King\'s Landing',
    'winterfell':'Winterfell', 'game of thrones':'Game of Thrones',
    '#gameofthrones':'Game of Thrones', 'Game of Thrones writers': 'D&D'}

# May need apache_beam.pvalue.AsDict

# Extract Twitter timestamps to prepare for Windowing

# class AddTimestampDoFn(beam.DoFn):
#   def __init__(self):
#       from datetime import datetime, timedelta
#       import dateutil.parser
#       from dateutil.tz import tzutc
#       import logging
#
#   def totimestamp(dt, epoch=datetime(1970,1,1, tzinfo=tzutc())):
#       td = dt - epoch
#       # return td.total_seconds()
#       return (td.microseconds + (td.seconds + td.days * 86400) * 10**6) / 10**6
#
#   def process(self, element):
#     # Extract the numeric Unix seconds-since-epoch timestamp to be
#     # associated with the current log entry.
#     tweet_time = dateutil.parser.parse(element['created_at'])
#     unix_timestamp = totimestamp(tweet_time)
#     # Wrap and emit the current entry and new timestamp in a
#     # TimestampedValue.
#     logging.debug('Added timestamp.')
#     yield beam.window.TimestampedValue(element, unix_timestamp)

# Emit values
def emit_values(tweet_json, entity_map):

    from vaderDF.vaderSentiment import SentimentIntensityAnalyzer

    tweet_input = json.loads(tweet_json)
    # print("\n\n\n")
    # print(type(tweet_input))
    # print("\n\n\n")
    # print(tweet_input)
    # print("\n\n\n")

    if u'text' in tweet_input:
        tweet_text = tweet_input[u'text']
    else:
        tweet_text = ""

    # logging.debug("Tweet_text")
    # logging.debug(tweet_text)

    break_set = {'@chrisevans:'}

    # Add actual sentiment analysis
    analyzer = SentimentIntensityAnalyzer()
    vs = analyzer.polarity_scores(tweet_text)
    if vs['compound'] == 0:
        logging.debug('Tweet w/ score of 0: %s',tweet_text)
        return

    # Emit that score for each entity in this tweet
    if tweet_text and tweet_text != "":
        for word in tweet_text.split(' '):
            lower_word = word.lower()
            if lower_word in break_set:
                logging.debug('Found a match to break set.')
                break
            elif lower_word in entity_map:
                logging.debug('Tweet: %s',tweet_text)
                logging.debug('%s : %s',entity_map[lower_word], vs['compound'])
                # Yield the entity properly spelled and capitalized,
                # and the combined score ranging from -1 to 1
                yield entity_map[lower_word], vs['compound']

class AddWindowTimestampFn(beam.DoFn):
  def process(self, element, window=beam.DoFn.WindowParam):
    import logging

    logging.debug('Adding window timestamp.')
    window_start = window.start.to_utc_datetime()
    #window_end = window.end.to_utc_datetime()
    return [(window_start.isoformat(' '),) + element]

class EntityScoreCombine(beam.CombineFn):
    def __init__(self):
        import logging

    def create_accumulator(self):
        logging.debug('Creating accumulator.')
        return (0, 0, 0, 0)

    def add_input(self, so_far, element):
        logging.debug('Adding input.')
        if element == 0:
            return so_far
        else:
            total, count = so_far[0]+element, so_far[1] + 1
            if so_far[2]==0:
                min_val = element
            else:
                min_val = min(so_far[2], element)
            if so_far[3]==0:
                max_val = element
            else:
                max_val = max(so_far[3], element)
            return (total, count, min_val, max_val)

    def merge_accumulators(self, accumulators):
        logging.debug('Merging accumulators.')
        totals, counts, mins, maxes = zip(*accumulators)
        return (sum(totals), sum(counts), min(mins), max(maxes))

    def extract_output(self, accumulated_counts):
        logging.debug('Extracting output.')
        total, count, min, max = accumulated_counts
        if count != 0:
            return (min, round(float(total) / float(count), 3), max, count)
        else:
            return (min, 0, max, count)

def format_for_write(element):
    import logging
    return_const = {'interval_start':element[0],
                    'entity':element[1], 'low_senti':element[2][0],
                    'avg_senti':element[2][1], 'high_senti':element[2][2],
                    'num_datapoints':element[2][3]}
    logging.debug('Formatted to write: %s', return_const)
    return return_const

# | 'BQ Source' >> beam.io.Read(bq_source)
# | 'extract timestamps' >> beam.ParDo(AddTimestampDoFn())

def main():
    # bq_source = BigQuerySource(query="""
    #                            SELECT created_at, text
    #                            FROM got_sentiment.got_tweets
    #                            """,
    #                            validate=False, coder=None,
    #                            use_standard_sql=True, flatten_results=True,
    #                            kms_key=None)

    # Removed attributes from ReadFromPubSub:
    #                              with_attributes=False,
    #                             timestamp_attribute='created_at'


    # Create the Pipeline with the specified options.
    with Pipeline(options=options) as p:
        results = (p | 'read_from_topic' >> ReadFromPubSub(topic=PUBSUB_TOPIC)
                     | 'Window' >> WindowInto(window.FixedWindows(60))
                     | 'Emit_needed_values' >> FlatMap(emit_values,entity_map)
                     | 'Combine' >> CombinePerKey(EntityScoreCombine())
                     | 'Add Window Timestamp' >> beam.ParDo(AddWindowTimestampFn())
                     | 'FormatForWrite' >> Map(format_for_write)
                     | 'Write' >> WriteToBigQuery('streaming_scores', dataset=BQ_DATASET,
                            project=PROJECT_ID,
                            create_disposition='CREATE_IF_NEEDED',
                            write_disposition='WRITE_APPEND',
                            batch_size=20)
                    )

if __name__ == '__main__':
      logging.getLogger().setLevel(logging.DEBUG)
      main()
