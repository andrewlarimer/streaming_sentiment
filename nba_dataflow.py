from __future__ import division

import os
import json
import logging
from datetime import datetime, timedelta
import dateutil.parser
from dateutil.tz import tzutc

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
google_cloud_options.project = 'myspringml2'
google_cloud_options.job_name = 'nba-senti-job-' + datetime.now().strftime("%H-%M")
google_cloud_options.staging_location = 'gs://springml-nba-finals/binaries'
google_cloud_options.temp_location = 'gs://springml-nba-finals/temp'
options.view_as(StandardOptions).runner = 'DataflowRunner'
options.view_as(StandardOptions).streaming = True

# from apache_beam import window
# fixed_windowed_items = (
#     items | 'window' >> beam.WindowInto(window.FixedWindows(60)))

PUBSUB_TOPIC = 'projects/myspringml2/topics/nba_finals'
BQ_DATASET = 'nba_finals'
PROJECT_ID = 'myspringml2'

entity_map = {
"NBA Finals",
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
}

# May need apache_beam.pvalue.AsDict

# class AddTimestampDoFn(beam.DoFn):
# # Extract Twitter timestamps to prepare for Windowing
#   def totimestamp(self, dt, epoch=datetime(1970,1,1, tzinfo=tzutc())):
#     td = dt - epoch
#     # return td.total_seconds()
#     return (td.microseconds + (td.seconds + td.days * 86400) * 10**6) / 10**6
#
#   def process(self, element):
#     # Extract the numeric Unix seconds-since-epoch timestamp to be
#     # associated with the current log entry.
#     tweet_time = dateutil.parser.parse(element['created_at'])
#     unix_timestamp = totimestamp(tweet_time)
#     # Wrap and emit the current entry and new timestamp in a
#     # TimestampedValue.
#     yield beam.window.TimestampedValue(element, unix_timestamp)

# Emit values
def emit_values(tweet_json, entity_map):

    import logging
    import base64
    import re
    from vaderDF.vaderSentiment import SentimentIntensityAnalyzer

    decoded_tweet = base64.urlsafe_b64decode(tweet_json)
    tweet_input = json.loads(decoded_tweet)
    tweet_text = tweet_input['text']

    # Add actual sentiment analysis
    analyzer = SentimentIntensityAnalyzer()
    vs = analyzer.polarity_scores(tweet_input['text'])
    if vs['compound'] == 0:
        logging.debug('Tweet w/ score of 0: %s',tweet_text)
        return

    # Emit that score for each entity in this tweet
    if tweet_text and tweet_text != "":
        for entity in entity_map:
            if re.search(entity.lower(), tweet_text.lower()):
                logging.debug('Tweet: %s',tweet_text)
                logging.debug('%s : %s',entity, vs['compound'])
                # Yield the entity properly spelled and capitalized,
                # and the combined score ranging from -1 to 1
                yield entity, vs['compound']

class AddWindowTimestampFn(beam.DoFn):
  def process(self, element, window=beam.DoFn.WindowParam):
    window_start = window.start.to_utc_datetime()
    #window_end = window.end.to_utc_datetime()
    return [(window_start.isoformat(' '),) + element]

class EntityScoreCombine(beam.CombineFn):
    def create_accumulator(self):
        return (0, 0, None, None)

    def add_input(self, so_far, element):
        if element == 0:
            return so_far
        else:
            total, count = so_far[0]+element, so_far[1] + 1
            if not so_far[2]:
                min_val = element
            else:
                min_val = min(so_far[2], element)
            if not so_far[3]:
                max_val = element
            else:
                max_val = max(so_far[3], element)
            return (total, count, min_val, max_val)

    def merge_accumulators(self, accumulators):
        totals, counts, mins, maxes = zip(*accumulators)
        return (sum(totals), sum(counts), min(mins), max(maxes))

    def extract_output(self, accumulated_counts):
        total, count, min, max = accumulated_counts
        if count != 0:
            return (min, round(float(total) / float(count), 3), max, count)
        else:
            return (min, 0, max, count)

def format_for_write(element):
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

    # Create the Pipeline with the specified options.
    with Pipeline(options=options) as p:
        results = p | 'read_from_topic' >> ReadFromPubSub(topic=PUBSUB_TOPIC,
                             timestamp_attribute='created_at') \
                     | 'Window' >> WindowInto(window.FixedWindows(60)) \
                     | 'Emit_needed_values' >> FlatMap(emit_values,entity_map) \
                     | 'Combine' >> CombinePerKey(EntityScoreCombine()) \
                     | 'Add Window Timestamp' >> beam.ParDo(AddWindowTimestampFn()) \
                     | 'FormatForWrite' >> Map(format_for_write) \
                     | 'Write' >> WriteToBigQuery('streaming_scores', dataset=BQ_DATASET,
                            project=PROJECT_ID,
                            create_disposition='CREATE_IF_NEEDED',
                            write_disposition='WRITE_APPEND',
                            batch_size=10)


if __name__ == '__main__':
      logging.getLogger().setLevel(logging.DEBUG)
      main()
