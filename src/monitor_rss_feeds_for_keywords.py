import os
import json
import pytz
import boto3
import botocore
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.request import Request, urlopen

### --- start of constants and variables declaration --- ###
headers = {'User-Agent': 'Mozilla/5.0'}
slack_webhook_url = os.environ["SLACK_WEBHOOK_URL"]
artefacts_s3_bucket = os.environ["ARTEFACTS_S3_BUCKET"]
artefacts_s3_key_prefix = os.environ["ARTEFACTS_S3_KEY_PREFIX"]

lastpubdate_file_s3_key = artefacts_s3_key_prefix + "/lastpubdate.json"

lastpubdate_default = "Thu, 01 Jan 1970 00:00:00 +1000"  # default time from when to check for new items in an RSS feed
lastpubdate_data = {} # for each feed, this list will contain the latest item's publish date that was processed in the last run
most_recent_item_pubdate_data = {} # for each feed, this list will track the publish date of the latest item processed in this run
total_items_processed_this_run = {} # for each feed, this list will be used to track how many items were processed
total_items_matched_keywords_this_run = {} # for each feed, this list will be used to track the number of items that matched keywords

# Instructions for onboarding a new RSS feed for monitoring:
#   1. add details to RSSFeeds dictionary
#   2. add keywords to monitor in tne feedKeywords dictionary. Keywords are case insensitive.
#
# Note: 
# 1. Removing a feed that had been previously processed from the RSSFeeds dictionary doesn't remove its statistics from lastpubdate file


# When adding RSS feed details to RSSFeeds dictionary, use the following format:
#   'feed shorthand' : 'feed url'
# Keep the feed shorthand to at most 4 characters as this will be used to prefix the slack notifications

RSSFeeds = {
    'SMH':  'https://www.smh.com.au/rss/feed.xml',
    'AWS':  'http://www.awsarchitectureblog.com/atom.xml',
    'NEWS': 'http://www.news.com.au/feed/'
}

# When adding keywords to monitor in feedKeywords, use the following format: 
#   'feedName shorthand' : ['keyword1','keyword2',...,'keywordn']

feedKeywords = {
    'SMH': ['Covid', 'Lockdown', 'Space'],
    'AWS': ['Serverless', 'Microservices'],
    'NEWS': ['Covid', 'Lockdown']
}
### --- end of constants and variables declaration --- ###

def send_slack_message(slack_message):
    print('>send_slack_message:slack_message:' + slack_message)

    slack_payload = {"text": slack_message}

    response = requests.post(slack_webhook_url, json.dumps(slack_payload))
    response_json = response.text
    print('>send_slack_message:response after posting to slack:' + str(response_json))

def find_keywords(feedName, item, keywords_list):
    global lastpubdate_data
    global most_recent_item_pubdate_data
    global total_items_processed_this_run
    global total_items_matched_keywords_this_run

    # use the attributes of the item to create a string to search the keywords in
    # first, add the item's title and description
    try:
        line = item.title.contents[0] + item.description.contents[0]
    except Exception as error:
        # this item's title and description has to be obtained using a different pattern
        line = str(item.title) + str(item.description)
        print('>find_keyword:['+ str(feedName) + ']Error:' + str(item.title) + ':title.description.contents[0]:' + str(error) + ':UsedAlternateMethod:' + str(line))

    # next, add the item's categories to the string that we will be searching in
    all_categories = item.find_all('category')

    for category in all_categories:
        line += " " + category.contents[0]

    # increment the total number of items processed for this RSS feed, in this run
    total_items_processed_this_run[feedName] += 1
    
   # load the latest publish date that was processed for this feed in the last run. This will allow us to find any new items since the last run
    try:
        lastpubdate_processed_date = datetime.strptime(lastpubdate_data[feedName], "%a, %d %b %Y %H:%M:%S %z")
    except Exception as e:
        print('>find_keywords:['+str(feedName)+']Error getting lastpubdate:'+ str(e))
        # this is because there are no statistics for a newly onboarded RSS feed. Set it to defaults
        lastpubdate_data[feedName] = lastpubdate_default
        lastpubdate_processed_date = datetime.strptime(lastpubdate_data[feedName], "%a, %d %b %Y %H:%M:%S %z")
        most_recent_item_pubdate_data[feedName] = lastpubdate_default
    
    item_pubdate_date = datetime.strptime(item.pubdate.contents[0], "%a, %d %b %Y %H:%M:%S %z")

    # process this item only if it is newer than the publish date of the latest item processed for this feed in the last run
    if (item_pubdate_date > lastpubdate_processed_date):
        # this item is new
        print('>find_keywords:[' + str(feedName) + ']['+ str(lastpubdate_processed_date) + '][' + str(item_pubdate_date) + ']' + item.title.contents[0] + ' - New (processing)')

        # keep track of the most recent item that was processed for this feed in this run. Its publish date will written to file and will become
        # the date that will be used to check for newer items for this feed in the next lambda run
        if (item_pubdate_date > datetime.strptime(most_recent_item_pubdate_data[feedName], "%a, %d %b %Y %H:%M:%S %z")):
            most_recent_item_pubdate_data[feedName] = item.pubdate.contents[0]

        # check to see if any of the keywords match for this item
        keywords_matched = '' # this will hold the keywords that have matched for this item
        for keyword in keywords_list:
            keyword_search_result = line.lower().find(keyword.lower())

            if (keyword_search_result != -1):
                # a keyword was found
                total_items_matched_keywords_this_run[feedName] += 1
                keywords_matched += keyword + ','

        if keywords_matched != '':
            # there were some keywords found for this item
            keywords_matched = keywords_matched[:-1]   # Remove the trailing ',' which is added whenever a keyword is found
            item_title = item.title.contents[0]
            item_link = item.contents[4][:-2]
            
            # remove all ' from item.title as this causes issues with posting to slack
            item_title = item_title.replace("'","")

            print('>find_keywords:[' + str(feedName) + '][' + str(lastpubdate_processed_date) + '][' + str(item_pubdate_date) + ']' + item.title.contents[0] + ' - keywords matched:'+keywords_matched)
            
            # create the message to send to slack
            slack_message = '[' + keywords_matched + '@' + feedName + '] ' + item_title + ' ' + item_link
            send_slack_message(slack_message)
        else:
            print('>find_keywords:[' + str(feedName) + '][' + str(lastpubdate_processed_date) + '][' + str(item_pubdate_date) + ']' + item.title.contents[0] + ' - no matching keywords found')
            
    else:
        # do nothing as this item is old
        print('>find_keywords:[' + str(feedName) + '][' + str(lastpubdate_processed_date) + '][' + str(item_pubdate_date) + ']' + item.title.contents[0] + ' - Skipping(old)')

def process_rss_feed(feedName):

    url = RSSFeeds[feedName]
    print('>process_rss_feed:[feedName=' + feedName + '][url=' + url + ']')

    # read the RSS feed and download the items (if there are any)
    response = Request(url, headers=headers)
    webpage  = urlopen(response).read()

    soup = BeautifulSoup(webpage, 'html.parser')

    # individual items in an RSS feed are packaged inside <item> </item> tags. Find individual <item> </item> blocks and process them
    all_items = soup.find_all('item')

    for item in all_items:
        find_keywords(feedName, item, feedKeywords[feedName])
        
def process_rss_feeds_for_keywords():
    global lastpubdate_data
    global most_recent_item_pubdate_data

    # Read lastpubdate file to get the statistics from the last run of this lambda.
    # This will give us the publish date of the latest item (for each monitored feed) that was processed. This will be used to find any new items
    # that would have been published since the last time this lambda was run.
    # If lastpubdate file doesn't exist then treat all monitored feeds as if they haven't been previously processed.
    
    print('>process_rss_feeds_for_keywords:Start processing of RSS feeds')

    # lets check if the lastpubdate file exists
    s3 = boto3.resource('s3')

    try:
        s3.Object(artefacts_s3_bucket,lastpubdate_file_s3_key).load()

        print('>process_rss_feeds_for_keywords:lastpubdate file found. Reading in values')

        lastpubdate_file_contents = s3.Object(artefacts_s3_bucket, lastpubdate_file_s3_key).get()['Body'].read().decode('utf-8')
        lastpubdate_data = json.loads(lastpubdate_file_contents)

        # keep a record of the latest item processed for each feed in this run. This will be used to update the lastpubdate file.
        # initialise this with the latest item's data from last run.
        most_recent_item_pubdate_data = json.loads(lastpubdate_file_contents)

    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == "404":
            # lastpubdate file does not exist. We will treat all feeds as if they have not been processed previously.
            print('>process_rss_feeds_for_keywords:No lastpubdate file found. Treating all feeds as if they have never been processed before.')
            for feedName in RSSFeeds:
                lastpubdate_data[feedName] = lastpubdate_default
                most_recent_item_pubdate_data[feedName] = lastpubdate_default

    # for this run, initialise statistics for each monitored feed
    for feedName in RSSFeeds:
        total_items_processed_this_run[feedName] = 0
        total_items_matched_keywords_this_run[feedName] = 0

    print('>process_rss_feeds_for_keywords:lastpubdate_data:', lastpubdate_data)
    print('>process_rss_feeds_for_keywords:most_recent_item_pubdate_data:',most_recent_item_pubdate_data, '\n')

    # process each monitored RSS feed to find if there are any new items that match the specified keywords
    for feedName in RSSFeeds:
        process_rss_feed(feedName)
    
    print('\n>process_rss_feeds_for_keywords:update lastpubdate_data file')

    lastpubdate_s3_file = s3.Object(artefacts_s3_bucket,lastpubdate_file_s3_key)
    lastpubdate_s3_file.put(Body=(bytes(json.dumps(most_recent_item_pubdate_data).encode('UTF-8'))))

    statistics = '\n>Summary'
    statistics += '>>Previous runs latest item publish date:' + str(lastpubdate_data)
    statistics += '>>This runs latest item publish date:' + str(most_recent_item_pubdate_data)
    statistics += '>>Total items processed in this run:' + str(total_items_processed_this_run)
    statistics += '>>Total items that matched keywords in this run:' + str(total_items_matched_keywords_this_run)

    return statistics

def lambda_handler(event, context):
    statistics = process_rss_feeds_for_keywords()
    return {
        'statusCode': 200,
        'body': json.dumps(
            statistics
        )
    }
