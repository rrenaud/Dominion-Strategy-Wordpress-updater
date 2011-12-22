import collections
import csv
from datetime import date
import difflib
import os
import pickle
import re
import time
import textwrap
import xmlrpclib
import argparse

from BeautifulSoup import BeautifulSoup

argparser = argparse.ArgumentParser()
argparser.add_argument('--save_edits', action='store_true', dest='save_edits')

user = open('user.txt').read().strip()
pw = open('wp_pw.txt').read().strip()

def CheckForUnlinkedMatch(card_name, pluralizer, contained, bs_content, post):
    def TextMatcher(st):
        if card_name in st or pluralizer[card_name] in st: 
            # we matched card name
            for super_card_name in contained:
                if super_card_name in st or pluralizer[card_name] in st:  
                    # check that we didn't get a bogus match, matching
                    # market in a the text 'Grand Market'
                    return False
            return True
        return False

    matches = bs_content.findAll(text=TextMatcher)
                                 
    if not matches:
        return

    # Check if the match is inside a link.
    for m in matches:
        p = m
        while p != None:
            if hasattr(p, 'name'):
                if p.name == 'a':
                    return False
            p = p.parent

    # Check if a link would match against the name
    # Simply _Possess_{http://dominionstrategy.wordpress.com/2010/12/03/alchemy-possession/} him
    for a_tag in bs_content.findAll('a'):
        if card_name.lower().replace(' ', '') in a_tag.get('href', '').lower():
            return False

    return True

def main():
    stub = xmlrpclib.ServerProxy(
        'http://dominionstrategy.wordpress.com/xmlrpc.php')
    # blog_info = stub.wp.getUsersBlogs(user, pw)
    # ds_blog_info = [x for x in blog_info if x['url'] == 
    #                 'http://dominionstrategy.wordpress.com/'][0]
    # print ds_blog_info
    # blog_id = ds_blog_info['blogid']
    blog_id = '17443029'

    card_list = list(csv.DictReader(open('card_list.csv', 'r').readlines()))

    # We need to figure out things like 'Village' is contained in 
    # 'Mining Village', and 'Market' is contained in 'Black Market', so we
    # don't do something stupid like make a link from the Market in 
    # 'Black Market' to the Market itself, rather than to the Black Market
    contained_lists = collections.defaultdict(list)
    cards = []
    pluralizer = {}
    for row in card_list:
        s = row['Singular']
        cards.append(row['Singular'])
        pluralizer[s] = row['Plural']
        for row2 in card_list:
            s2 = row2['Singular']
            if s != s2 and s in s2:
                contained_lists[s].append(s2)

    # cache the posts so that we don't re-download 100 posts every time
    # we try to run the script.  This does mean however, that you'll
    # need to delete the cache after running it when a new post so it
    # actually downloads the post.  
    # TODO: Maybe improve this by requesting only
    # the most recent post, determining if it's in the cache, and then
    # if it's not in the cache do we then pull down all of the posts?  I am
    # lazy...
    MAX_POSTS = 1000
    post_cache = 'recent_posts_cache'
    if os.path.exists(post_cache):
        print 'reading cached data'
        recent_posts = pickle.loads(open(post_cache, 'r').read())
    else:
        recent_posts = stub.metaWeblog.getRecentPosts(blog_id, user, pw, 
                                                      MAX_POSTS)
        open(post_cache, 'w').write(pickle.dumps(recent_posts))

    published_posts = [p for p in recent_posts if p['post_status'] == 'publish']

    card_posts = {}
    card_post_starts = ['Dominion:', 'Intrigue:', 'Seaside:', 'Alchemy:',
                        'Prosperity:', 'Guest Article:', 'Cornucopia:',
                        'Hinterlands:']

    # Only make links to published posts
    for post in published_posts:
         for potential_start in card_post_starts:
             if post['title'].startswith(potential_start):
                 #print 'got card post', post['title']
                 card = post['title'][len(potential_start):].strip()
                 if card in cards:
                     card_posts[card] = post
    ct = 0

    args = argparser.parse_args()
    diffs_dir = 'diffs'
    if os.path.exists(diffs_dir):
        os.system('rm -rf %s' % diffs_dir)
    os.mkdir(diffs_dir)
    for idx, post in enumerate(recent_posts):
        bs_content = BeautifulSoup(post['description'])
        unmatched_cards = []
        for card in card_posts:
            if card_posts[card] == post:
                #print 'skipping indentity post', card, post['title']
                continue
            if CheckForUnlinkedMatch(card, pluralizer, 
                                     contained_lists[card], 
                                     bs_content, post):
                ct += 1
                unmatched_cards.append(card)

        new_content = post['description']
        for ucard in unmatched_cards:
            ucard_url = card_posts[ucard]['permaLink']
            # We are assuming the first time the term appears in the
            # doc it's the place that we want to anchor to, but this
            # doesn't apply the 'don't overmatch stupidly' logic, and 
            # could make us look dumb.
            def ReplacementFunc(match):
                return '<a href="%s">%s</a>' % (ucard_url, match.group())
            matcher = re.compile(ucard + '|' + pluralizer[ucard])
            match = matcher.search(new_content)
            orig_content = new_content
            new_content = matcher.sub(ReplacementFunc, new_content, 1)

            print 'From\n' + '\n\t'.join(textwrap.wrap(
                orig_content[match.start() - 50:match.end() + 50]))

            print 'To\n' + '\n\t'.join(textwrap.wrap(
                new_content[match.start() - 50:match.end() + 150]))
            print

        def IsoURLToCRUrl(match):
            return 'councilroom.com/game?game_id=%s' % match.group('fn')
                
        iso_link_matcher = re.compile(
            'dominion\.isotropic\.org\/gamelog\/[0-9]*\/[0-9]*\/(?P<fn>.*)')
        new_content = iso_link_matcher.sub(IsoURLToCRUrl, new_content)

        if new_content != post['description']:
            orig_content = post['description']
            post['description'] = new_content
            print 'want to edit post', post['title']
            if args.save_edits:
                stub.metaWeblog.editPost(post['postid'], user, pw, post)
            else:
                print 'preview run'

            diff_str = difflib.HtmlDiff().make_file(
                textwrap.wrap(orig_content),
                textwrap.wrap(new_content))
            out_fn = (post['title'] + '.diff.html').replace('/', '-').replace(
                ' ', '_')
            out_fn = diffs_dir + '/' + out_fn
            open(out_fn, 'w').write(diff_str.encode('utf-8'))

    print ct, 'changes made'
                       
if __name__ == '__main__':
    main()
