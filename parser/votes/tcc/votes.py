#! /usr/bin/env python
# -*- coding: utf-8 -*-
import sys
sys.path.append('../../')
import re
import codecs
import unicodedata
import json
import glob
import psycopg2
import db_settings
import common


def UpsertVote(data):
    c.execute('''
        UPDATE votes_votes
        SET sitting_id = %(sitting_id)s, date = %(date)s, vote_seq = %(vote_seq)s, content = %(content)s, conflict = null
        WHERE uid = %(uid)s
    ''', data)
    c.execute('''
        INSERT INTO votes_votes(uid, sitting_id, date, vote_seq, content)
        SELECT %(uid)s, %(sitting_id)s, %(date)s, %(vote_seq)s, %(content)s
        WHERE NOT EXISTS (SELECT 1 FROM votes_votes WHERE uid = %(uid)s)
    ''', data)

def VoteVoterRelation(councilor_id, vote_id, decision):
    c.execute('''
        UPDATE votes_councilors_votes
        SET decision = %s, conflict = null
        WHERE councilor_id = %s AND vote_id = %s
    ''', (decision, councilor_id, vote_id))
    c.execute('''
        INSERT INTO votes_councilors_votes(councilor_id, vote_id, decision)
        SELECT %s, %s, %s
        WHERE NOT EXISTS (SELECT 1 FROM votes_councilors_votes WHERE councilor_id = %s AND vote_id = %s)
    ''',(councilor_id, vote_id, decision, councilor_id, vote_id))

def GetVoteContent(text):
    lines = [line.lstrip() for line in text.split('\n')]
    for i in reversed(range((0-len(lines)), -2)):
        if re.search(u'^議決', lines[i]):
            return '\n'.join(lines[i+1:])
        if re.search(u'(請.*審議|審議.*案)', lines[i]):
            return '\n'.join(lines[i:])
    for i in reversed(range((0-len(lines)), -1)):
        if re.search(u'^發言議員', lines[i]):
            return '\n'.join(lines[i-1:])
    for i in reversed(range((0-len(lines)), -1)):
        if re.search(u'(議員.*提議|其他事項$)', lines[i]):
            return '\n'.join(lines[i:])
    return lines[-1]


def IterVote(text, sitting_dict):
    print sitting_dict["uid"]
    vote_count = 1
    pre_match_end = 0
    for match in Namelist_Token.finditer(text):
        vote_seq = str(vote_count).zfill(3)
        vote_dict = {'uid': '%s-%s' % (sitting_dict["uid"], vote_seq), 'sitting_id': sitting_dict["uid"], 'vote_seq': vote_seq, 'date': sitting_dict["date"], 'content': GetVoteContent(text[pre_match_end:match.end()])}
        UpsertVote(vote_dict)
        ref = {'agree': 1, 'disagree': -1, 'abstain': 0}
        for key, value in ref.items():
            if match.group(key):
                for id, councilor_id in common.getIdList(c, common.getNameList(re.sub(u'[、：，:,]', ' ', match.group(key))), sitting_dict):
                    VoteVoterRelation(id, vote_dict['uid'], value)
        vote_count += 1
        pre_match_end = match.end()

conn = db_settings.con()
c = conn.cursor()
election_years = {1: '1969', 2: '1973', 3: '1977', 4: '1981', 5: '1985', 6: '1989', 7: '1994', 8: '1998', 9: '2002', 10: '2006', 11: '2010', 12: '2014'}
election_year = '2010'
county, county_abbreviation = u'臺北市', 'TPE'
total_text = unicodedata.normalize('NFC', codecs.open(u"../../../data/tcc/meeting_minutes-%s.txt" % election_year, "r", "utf-8").read())

Session_Token = re.compile(u'''
    [\s]*
    (?P<name>
        %s議會
        第(?P<ad>[\d]+)屆
        第(?P<session>[\d]+)次(?P<type>(定期|臨時))大會
        (預備會議暨)?
        第(?P<times>[\d]+)次
        會議
    )
    紀錄
''' % county, re.X)

Present_Token = re.compile(u'''
    出席議員[:：]?
    (?P<names>.+?)
    (計[\d]+位)?
    (請假議員)?
    列席
''', re.X|re.S)

Absent_Token = re.compile(u'''
    請假議員[:：]
    (?P<names>.+)
    (計[\d]+位)?
    列席
''', re.X|re.S)

Namelist_Token = re.compile(u'''
    ^.*
    (?P<agree>贊成議員.*)
    (?P<disagree>反對議員[^(棄權議員)\n]*)
    (?P<abstain>棄權議員.*([\d]+位|無))?
    .*$
''', re.X | re.M)

sittings = []
for match in Session_Token.finditer(total_text):
    if match:
        if match.group('type') == u'定期':
            uid = '%s-%s-%02d-CS-%02d' % (county_abbreviation, election_years[int(match.group('ad'))], int(match.group('session')), int(match.group('times')))
        elif match.group('type') == u'臨時':
            uid = '%s-%s-T%02d-CS-%02d' % (county_abbreviation, election_years[int(match.group('ad'))], int(match.group('session')), int(match.group('times')))
        sittings.append({"uid":uid, "name": re.sub('\s', '', match.group('name')), "county": county, "election_year": election_years[int(match.group('ad'))], "session": match.group('session'), "date": common.ROC2AD(total_text[match.end():]), "start": match.start(), "end": match.end()})
for i in range(0, len(sittings)):
    # --> sittings, attendance, filelog
    if i != len(sittings)-1:
        one_sitting_text = total_text[sittings[i]['start']:sittings[i+1]['start']]
    else:
        one_sitting_text = total_text[sittings[i]['start']:]
    common.InsertSitting(c, sittings[i])
    common.FileLog(c, sittings[i]['name'])
    present_match = Present_Token.search(one_sitting_text)
    if present_match:
        common.Attendance(c, sittings[i], present_match.group('names'), 'CS', 'present')
    absent_match = Absent_Token.search(one_sitting_text)
    if absent_match:
        common.Attendance(c, sittings[i], absent_match.group('names'), 'CS', 'absent')
    # <--
    # --> votes
    IterVote(one_sitting_text, sittings[i])
    # <--
conn.commit()
print 'votes, voter done!'

# --> conscience vote
print u'Conscience vote processing...'
def party_Decision_List(party, election_year):
    c.execute('''
        select vote_id, avg(decision)
        from votes_councilors_votes
        where decision is not null and councilor_id in (select id from councilors_councilorsdetail where party = %s and election_year = %s)
        group by vote_id
    ''', (party, election_year))
    return c.fetchall()

def personal_Decision_List(party, vote_id, election_year):
    c.execute('''
        select councilor_id, decision
        from votes_councilors_votes
        where decision is not null and vote_id = %s and councilor_id in (select id from councilors_councilorsdetail where party = %s and election_year = %s)
    ''', (vote_id, party, election_year))
    return c.fetchall()

def party_List(election_year, county):
    c.execute('''
        select party, count(*)
        from councilors_councilorsdetail
        where election_year = %s and county = %s and party != '無黨籍'
        group by party
    ''', (election_year, county))
    return c.fetchall()

def conflict_vote(conflict, vote_id):
    c.execute('''
        update votes_votes
        set conflict = %s
        where uid = %s
    ''', (conflict, vote_id))

def conflict_voter(conflict, councilor_id, vote_id):
    c.execute('''
        update votes_councilors_votes
        set conflict = %s
        where councilor_id = %s and vote_id = %s
    ''', (conflict, councilor_id, vote_id))

for party, count in party_List(election_year, county):
    if count > 2:
        for vote_id, avg_decision in party_Decision_List(party, election_year):
            # 黨的decision平均值如不為整數，表示該表決有人脫黨投票
            if int(avg_decision) != avg_decision:
                conflict_vote(True, vote_id)
                # 同黨各立委的decision與黨的decision平均值相乘如小於(相反票)等於(棄權票)零，表示脫黨投票
                for councilor_id, personal_decision in personal_Decision_List(party, vote_id, election_year):
                    if personal_decision*avg_decision <= 0:
                        conflict_voter(True, councilor_id, vote_id)
conn.commit()
print 'done!'
# <-- conscience vote

# --> not voting & vote results
print u'Not voting & vote results processing...'
def vote_list():
    c.execute('''
        select vote.uid, sitting.election_year, sitting.date
        from votes_votes vote, sittings_sittings sitting
        where vote.sitting_id = sitting.uid and sitting.county = %s
    ''', (county,))
    return c.fetchall()

def not_voting_list(vote_id, vote_ad, vote_date):
    c.execute('''
        select id
        from councilors_councilorsdetail
        where election_year = %s and county = %s and term_start <= %s and cast(term_end::json->>'date' as date) > %s and id not in (select councilor_id from votes_councilors_votes where vote_id = %s)
    ''', (vote_ad, county, vote_date, vote_date, vote_id))
    return c.fetchall()

def insert_not_voting_record(councilor_id, vote_id):
    c.execute('''
        INSERT INTO votes_councilors_votes(councilor_id, vote_id)
        SELECT %s, %s
        WHERE NOT EXISTS (SELECT councilor_id, vote_id FROM votes_councilors_votes WHERE councilor_id = %s AND vote_id = %s)
    ''', (councilor_id, vote_id, councilor_id, vote_id))

def get_vote_results(vote_id):
    c.execute('''
        select
            count(*) total,
            sum(case when decision isnull then 1 else 0 end) not_voting,
            sum(case when decision = 1 then 1 else 0 end) agree,
            sum(case when decision = 0 then 1 else 0 end) abstain,
            sum(case when decision = -1 then 1 else 0 end) disagree
        from votes_councilors_votes
        where vote_id = %s
    ''', (vote_id,))
    return [desc[0] for desc in c.description], c.fetchone() # return column name and value

def update_vote_results(uid, results):
    if results['agree'] > results['disagree']:
        result = 'Passed'
    else:
        result = 'Not Passed'
    c.execute('''
        UPDATE votes_votes
        SET result = %s, results = %s
        WHERE uid = %s
    ''', (result, results, uid))

for vote_id, vote_ad, vote_date in vote_list():
    for councilor_id in not_voting_list(vote_id, vote_ad, vote_date):
        insert_not_voting_record(councilor_id, vote_id)
    key, value = get_vote_results(vote_id)
    update_vote_results(vote_id, dict(zip(key, value)))
conn.commit()
print 'done!'
# <-- not voting & vote results end

# --> update meeting_minutes download links
print 'update meeting_minutes download links'
meetings = json.load(open('../../../data/tcc/meeting_minutes-%s.json' % election_year))
for meeting in meetings:
    meeting['links'] = {'url': meeting['download_url'], 'note': u'議會官網會議紀錄'}
    meeting['name'] = re.sub(u'第0+', u'第', u'%s議會%s%s' % (meeting['county'], meeting['sitting'], meeting['meeting']))
    meeting['name'] = re.sub(u'紀錄$', '', meeting['name'])
    print meeting['name']
    common.UpdateSittingLinks(c, meeting)
conn.commit()
print 'done!'
# <-- update meeting_minutes download links end

print 'Succeed'
