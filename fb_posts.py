import urllib.request
import json
import datetime
import csv
import time
import os
from time import gmtime, strftime
from fb_posts_realtime import init_kafka, send_message
from fb_comments_page import scrapeFacebookPageFeedComments
from run_es import init_es, index_res
from save_pg import save_post_pg
class FB_SCRAPE(object):
    def __init__(self, useKafka, useES, useSQL, outputJSON):
        self.producer = None
        self.es = None
        if useKafka:
            self.producer = init_kafka(os.environ['KAFKA_PORT'])
        if useES:
            self.es = init_es()
        self.ES = useES
        self.useSQL = useSQL
        self.JSON = outputJSON
        self.file_id = ""
        self.access_token = ""
        self.tstamp = ""
        self.sesh = strftime("%Y-%m-%d-%H", gmtime())
        self.dir = "data/files/" + self.sesh + "/"

        if not os.path.exists(self.dir):
            os.makedirs(self.dir)

    def request_until_succeed(self, url):
        req = urllib.request.Request(url)
        success = False
        while success is False:
            try:
                response = urllib.request.urlopen(req)
                if response.getcode() == 200:
                    success = True
            except Exception as e:
                print(e)
                time.sleep(5)

                #print("Error for URL %s: %s" % (url, datetime.datetime.now()))
                print("Retrying.")

        return response.read().decode(response.headers.get_content_charset())


    # Needed to write tricky unicode correctly to csv
    def unicode_normalize(self, text):
        return text.translate({ 0x2018:0x27, 0x2019:0x27, 0x201C:0x22, 0x201D:0x22,
                                0xa0:0x20 })

    def getFacebookPageFeedData(self, page_id, access_token, num_statuses,tStamp):

        # Construct the URL string; see http://stackoverflow.com/a/37239851 for
        # Reactions parameters
        base = "https://graph.facebook.com/v2.6"
        node = "/%s/feed" % page_id


        fields = "/?" + "fields=from,message,link,created_time,type,name,id," + \
                "comments.limit(0).summary(true),shares,reactions" + \
                ".limit(0).summary(true)"
        parameters =  "&limit=%s&since=%s&access_token=%s" % (num_statuses, tStamp, access_token)
        url = base + node + fields + parameters



        # retrieve data
        data = json.loads(self.request_until_succeed(url))

        return data

    def getReactionsForStatus(self, status_id, access_token):
        # See http://stackoverflow.com/a/37239851 for Reactions parameters
            # Reactions are only accessable at a single-post endpoint
        base = "https://graph.facebook.com/v2.6"
        node = "/%s" % status_id
        reactions = "/?fields=" \
                "reactions.type(LIKE).limit(0).summary(total_count).as(like)" \
                ",reactions.type(LOVE).limit(0).summary(total_count).as(love)" \
                ",reactions.type(WOW).limit(0).summary(total_count).as(wow)" \
                ",reactions.type(HAHA).limit(0).summary(total_count).as(haha)" \
                ",reactions.type(SAD).limit(0).summary(total_count).as(sad)" \
                ",reactions.type(ANGRY).limit(0).summary(total_count).as(angry)"
        parameters = "&access_token=%s" % access_token
        url = base + node + reactions + parameters

        # retrieve data
        data = json.loads(self.request_until_succeed(url))

        return data
    def get_reaction_ids(self, status_id, access_token):
        base = "https://graph.facebook.com/v2.6"
        node = "/%s" % status_id
        parameters = "&access_token=%s" % access_token
        reactions = "/reactions?fields=" \
                    "id,type"
        url = base + node + reactions + parameters
        data = json.loads(self.request_until_succeed(url))


        return data

    def processFacebookPageFeedStatus(self,status, access_token):

        # The status is now a Python dictionary, so for top-level items,
        # we can simply call the key.

        # Additionally, some items may not always exist,
        # so must check for existence first

        status_id = status['id']
        status["group_id"] = self.file_id
        status['reacts'] = self.get_reaction_ids(status_id, access_token)
        from_id = status['from']['id']
        status_message = '' if 'message' not in status.keys() else \
                self.unicode_normalize(status['message'])
        link_name = '' if 'name' not in status.keys() else \
                self.unicode_normalize(status['name'])
        status_type = status['type']
        status_link = '' if 'link' not in status.keys() else \
                self.unicode_normalize(status['link'])

        # Time needs special care since a) it's in UTC and
        # b) it's not easy to use in statistical programs.

        status_published = datetime.datetime.strptime(
                status['created_time'],'%Y-%m-%dT%H:%M:%S+0000')
        status_published = status_published + \
                datetime.timedelta(hours=-5) # EST
        status_published = status_published.strftime(
                '%Y-%m-%d %H:%M:%S') # best time format for spreadsheet programs

        # Nested items require chaining dictionary keys.

        num_reactions = 0 if 'reactions' not in status else \
                status['reactions']['summary']['total_count']
        num_comments = 0 if 'comments' not in status else \
                status['comments']['summary']['total_count']
        num_shares = 0 if 'shares' not in status else status['shares']['count']

        # Counts of each reaction separately; good for sentiment
        # Only check for reactions if past date of implementation:
        # http://newsroom.fb.com/news/2016/02/reactions-now-available-globally/


        reactions = self.getReactionsForStatus(status_id, access_token) if \
                status_published > '2016-02-24 00:00:00' else {}

        num_likes = 0 if 'like' not in reactions else \
                reactions['like']['summary']['total_count']

        # Special case: Set number of Likes to Number of reactions for pre-reaction
        # statuses

        num_likes = num_reactions if status_published < '2016-02-24 00:00:00' \
                else num_likes

        def get_num_total_reactions(reaction_type, reactions):
            if reaction_type not in reactions:
                return 0
            else:
                return reactions[reaction_type]['summary']['total_count']

        num_loves = get_num_total_reactions('love', reactions)
        num_wows = get_num_total_reactions('wow', reactions)
        num_hahas = get_num_total_reactions('haha', reactions)
        num_sads = get_num_total_reactions('sad', reactions)
        num_angrys = get_num_total_reactions('angry', reactions)
        # Use ES
        if self.es is not None:
            index_res(self.es, status_id, status)
        # Save the JSON file
        with open(self.dir + status_id + ".json", 'w') as f:
            json.dump(status, f, ensure_ascii=False)


        # Return a tuple of all processed data
        return (status_id, status_message, link_name, status_type, status_link,
                status_published, num_reactions, num_comments, num_shares,
                num_likes, num_loves, num_wows, num_hahas, num_sads, num_angrys, from_id)

    def scrapeFacebookPageFeedStatus2(self, page_id, access_token, tStamp):
        self.file_id = page_id
        self.access_token = access_token
        self.tstamp = tStamp

        with open(self.dir + str(self.tstamp) + '%s_facebook_statuses.csv' % page_id, 'w', newline='',encoding='utf-8') as file:
            w = csv.writer(file)
            w.writerow(["status_id", "status_message", "link_name", "status_type",
                        "status_link", "status_published", "num_reactions",
                        "num_comments", "num_shares", "num_likes", "num_loves",
                        "num_wows", "num_hahas", "num_sads", "num_angrys", "from_id"])

            has_next_page = True
            num_processed = 0   # keep a count on how many we've processed
            scrape_starttime = datetime.datetime.now()

            print("Scraping %s Facebook Page: %s\n" % (page_id, scrape_starttime))

            statuses = self.getFacebookPageFeedData(page_id, access_token, 100, tStamp)

            while has_next_page:
                for status in statuses['data']:

                    # Ensure it is a status with the expected metadata
                    if 'reactions' in status:
                        data = self.processFacebookPageFeedStatus(status, access_token)
                        w.writerow(data)
                        if self.producer is not None:
                            send_message(self.producer, data, page_id)

                    # output progress occasionally to make sure code is not
                    # stalling
                    num_processed += 1
                    if num_processed % 100 == 0:
                        print("%s Statuses Processed: %s" % \
                            (num_processed, datetime.datetime.now()))

                # if there is no next page, we're done.
                if 'paging' in statuses.keys():
                    statuses = json.loads(self.request_until_succeed(
                                            statuses['paging']['next']))
                else:
                    has_next_page = False


            print("\nDone!\n%s Statuses Processed in %s" % \
                (num_processed, datetime.datetime.now() - scrape_starttime))
            return(num_processed)
    def scrapeComments(self):
        scrapeFacebookPageFeedComments(self.file_id,self.access_token,self.tstamp, self.sesh)
    def connect_to_SQL(self, group, status_name, message, reactions, comments, likes, name):
        save_post_pg(group, status_name, message, reactions, comments, likes, name)
