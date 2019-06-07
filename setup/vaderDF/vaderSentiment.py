# coding: utf-8
# Author: C.J. Hutto
# Thanks to George Berry for reducing the time complexity from something like O(N^4) to O(N).
# Thanks to Ewan Klein and Pierpaolo Pantone for bringing VADER into NLTK. Those modifications were awesome.
# For license information, see LICENSE.TXT

u"""
If you use the VADER sentiment analysis tools, please cite:
Hutto, C.J. & Gilbert, E.E. (2014). VADER: A Parsimonious Rule-based Model for
Sentiment Analysis of Social Media Text. Eighth International Conference on
Weblogs and Social Media (ICWSM-14). Ann Arbor, MI, June 2014.
"""
from __future__ import with_statement
from __future__ import division
from __future__ import absolute_import
import os
import re
import math
import string
import requests
import json
import logging
from itertools import product
from inspect import getsourcefile
from io import open

# ##Constants##

# (empirically derived mean sentiment intensity rating increase for booster words)
B_INCR = 0.293
B_DECR = -0.293

# (empirically derived mean sentiment intensity rating increase for using ALLCAPs to emphasize a word)
C_INCR = 0.733
N_SCALAR = -0.74

# for removing punctuation
REGEX_REMOVE_PUNCTUATION = re.compile(u'[%s]' % re.escape(string.punctuation))

PUNC_LIST = [u".", u"!", u"?", u",", u";", u":", u"-", u"'", u"\"",
             u"!!", u"!!!", u"??", u"???", u"?!?", u"!?!", u"?!?!", u"!?!?"]
NEGATE = \
    [u"aint", u"arent", u"cannot", u"cant", u"couldnt", u"darent", u"didnt", u"doesnt",
     u"ain't", u"aren't", u"can't", u"couldn't", u"daren't", u"didn't", u"doesn't",
     u"dont", u"hadnt", u"hasnt", u"havent", u"isnt", u"mightnt", u"mustnt", u"neither",
     u"don't", u"hadn't", u"hasn't", u"haven't", u"isn't", u"mightn't", u"mustn't",
     u"neednt", u"needn't", u"never", u"none", u"nope", u"nor", u"not", u"nothing", u"nowhere",
     u"oughtnt", u"shant", u"shouldnt", u"uhuh", u"wasnt", u"werent",
     u"oughtn't", u"shan't", u"shouldn't", u"uh-uh", u"wasn't", u"weren't",
     u"without", u"wont", u"wouldnt", u"won't", u"wouldn't", u"rarely", u"seldom", u"despite"]

# booster/dampener 'intensifiers' or 'degree adverbs'
# http://en.wiktionary.org/wiki/Category:English_degree_adverbs

BOOSTER_DICT = \
    {u"absolutely": B_INCR, u"amazingly": B_INCR, u"awfully": B_INCR, u"completely": B_INCR, u"considerably": B_INCR,
     u"decidedly": B_INCR, u"deeply": B_INCR, u"effing": B_INCR, u"enormously": B_INCR,
     u"entirely": B_INCR, u"especially": B_INCR, u"exceptionally": B_INCR, u"extremely": B_INCR,
     u"fabulously": B_INCR, u"flipping": B_INCR, u"flippin": B_INCR,
     u"fricking": B_INCR, u"frickin": B_INCR, u"frigging": B_INCR, u"friggin": B_INCR, u"fully": B_INCR, u"fucking": B_INCR,
     u"greatly": B_INCR, u"hella": B_INCR, u"highly": B_INCR, u"hugely": B_INCR, u"incredibly": B_INCR,
     u"intensely": B_INCR, u"majorly": B_INCR, u"more": B_INCR, u"most": B_INCR, u"particularly": B_INCR,
     u"purely": B_INCR, u"quite": B_INCR, u"really": B_INCR, u"remarkably": B_INCR,
     u"so": B_INCR, u"substantially": B_INCR,
     u"thoroughly": B_INCR, u"totally": B_INCR, u"tremendously": B_INCR,
     u"uber": B_INCR, u"unbelievably": B_INCR, u"unusually": B_INCR, u"utterly": B_INCR,
     u"very": B_INCR,
     u"almost": B_DECR, u"barely": B_DECR, u"hardly": B_DECR, u"just enough": B_DECR,
     u"kind of": B_DECR, u"kinda": B_DECR, u"kindof": B_DECR, u"kind-of": B_DECR,
     u"less": B_DECR, u"little": B_DECR, u"marginally": B_DECR, u"occasionally": B_DECR, u"partly": B_DECR,
     u"scarcely": B_DECR, u"slightly": B_DECR, u"somewhat": B_DECR,
     u"sort of": B_DECR, u"sorta": B_DECR, u"sortof": B_DECR, u"sort-of": B_DECR}

# check for sentiment laden idioms that do not contain lexicon words (future work, not yet implemented)
SENTIMENT_LADEN_IDIOMS = {u"cut the mustard": 2, u"hand to mouth": -2,
                          u"back handed": -2, u"blow smoke": -2, u"blowing smoke": -2,
                          u"upper hand": 1, u"break a leg": 2,
                          u"cooking with gas": 2, u"in the black": 2, u"in the red": -2,
                          u"on the ball": 2, u"under the weather": -2}

# check for special case idioms containing lexicon words
SPECIAL_CASE_IDIOMS = {u"the shit": 3, u"the bomb": 3, u"bad ass": 1.5, u"yeah right": -2,
                       u"kiss of death": -1.5}


# #Static methods# #

def negated(input_words, include_nt=True):
    u"""
    Determine if input contains negation words
    """
    input_words = [unicode(w).lower() for w in input_words]
    neg_words = []
    neg_words.extend(NEGATE)
    for word in neg_words:
        if word in input_words:
            return True
    if include_nt:
        for word in input_words:
            if u"n't" in word:
                return True
    if u"least" in input_words:
        i = input_words.index(u"least")
        if i > 0 and input_words[i - 1] != u"at":
            return True
    return False


def normalize(score, alpha=15):
    u"""
    Normalize the score to be between -1 and 1 using an alpha that
    approximates the max expected value
    """
    norm_score = score / math.sqrt((score * score) + alpha)
    if norm_score < -1.0:
        return -1.0
    elif norm_score > 1.0:
        return 1.0
    else:
        return norm_score


def allcap_differential(words):
    u"""
    Check whether just some words in the input are ALL CAPS
    :param list words: The words to inspect
    :returns: `True` if some but not all items in `words` are ALL CAPS
    """
    is_different = False
    allcap_words = 0
    for word in words:
        if word.isupper():
            allcap_words += 1
    cap_differential = len(words) - allcap_words
    if 0 < cap_differential < len(words):
        is_different = True
    return is_different


def scalar_inc_dec(word, valence, is_cap_diff):
    u"""
    Check if the preceding words increase, decrease, or negate/nullify the
    valence
    """
    scalar = 0.0
    word_lower = word.lower()
    if word_lower in BOOSTER_DICT:
        scalar = BOOSTER_DICT[word_lower]
        if valence < 0:
            scalar *= -1
        # check if booster/dampener word is in ALLCAPS (while others aren't)
        if word.isupper() and is_cap_diff:
            if valence > 0:
                scalar += C_INCR
            else:
                scalar -= C_INCR
    return scalar


class SentiText(object):
    u"""
    Identify sentiment-relevant string-level properties of input text.
    """

    def __init__(self, text):
        if not isinstance(text, unicode):
            text = unicode(text).encode(u'utf-8')
        self.text = text
        self.words_and_emoticons = self._words_and_emoticons()
        # doesn't separate words from\
        # adjacent punctuation (keeps emoticons & contractions)
        self.is_cap_diff = allcap_differential(self.words_and_emoticons)

    def _words_plus_punc(self):
        u"""
        Returns mapping of form:
        {
            'cat,': 'cat',
            ',cat': 'cat',
        }
        """
        no_punc_text = REGEX_REMOVE_PUNCTUATION.sub(u'', self.text)
        # removes punctuation (but loses emoticons & contractions)
        words_only = no_punc_text.split()
        # remove singletons
        words_only = set(w for w in words_only if len(w) > 1)
        # the product gives ('cat', ',') and (',', 'cat')
        punc_before = dict((u''.join(p), p[1]) for p in product(PUNC_LIST, words_only))
        punc_after = dict((u''.join(p), p[0]) for p in product(words_only, PUNC_LIST))
        words_punc_dict = punc_before
        words_punc_dict.update(punc_after)
        return words_punc_dict

    def _words_and_emoticons(self):
        u"""
        Removes leading and trailing puncutation
        Leaves contractions and most emoticons
            Does not preserve punc-plus-letter emoticons (e.g. :D)
        """
        wes = self.text.split()
        words_punc_dict = self._words_plus_punc()
        wes = [we for we in wes if len(we) > 1]
        for i, we in enumerate(wes):
            if we in words_punc_dict:
                wes[i] = words_punc_dict[we]
        return wes


class SentimentIntensityAnalyzer(object):
    u"""
    Give a sentiment intensity score to sentences.
    """

    def __init__(self, lexicon_file=u"vader_lexicon.txt", emoji_lexicon=u"emoji_utf8_lexicon.txt"):

        _this_module_file_path_ = os.path.abspath(getsourcefile(lambda: 0))

        logging.debug(_this_module_file_path_)
        logging.debug(os.listdir("."))

        lexicon_full_filepath = os.path.join(os.path.dirname(_this_module_file_path_), u'lexicons', lexicon_file)
        with open(lexicon_full_filepath, encoding=u'utf-8') as f:
            self.lexicon_full_filepath = f.read()
        self.lexicon = self.make_lex_dict()

        emoji_full_filepath = os.path.join(os.path.dirname(_this_module_file_path_), u'lexicons', emoji_lexicon)
        with open(emoji_full_filepath, encoding=u'utf-8') as f:
            self.emoji_full_filepath = f.read()
        self.emojis = self.make_emoji_dict()

    def make_lex_dict(self):
        u"""
        Convert lexicon file to a dictionary
        """
        lex_dict = {}
        for line in self.lexicon_full_filepath.split(u'\n'):
            (word, measure) = line.strip().split(u'\t')[0:2]
            lex_dict[word] = float(measure)
        return lex_dict

    def make_emoji_dict(self):
        u"""
        Convert emoji lexicon file to a dictionary
        """
        emoji_dict = {}
        for line in self.emoji_full_filepath.split(u'\n'):
            (emoji, description) = line.strip().split(u'\t')[0:2]
            emoji_dict[emoji] = description
        return emoji_dict

    def polarity_scores(self, text):
        u"""
        Return a float for sentiment strength based on the input text.
        Positive values are positive valence, negative value are negative
        valence.
        """
        # convert emojis to their textual descriptions
        text_token_list = text.split()
        text_no_emoji_lst = []
        for token in text_token_list:
            if token in self.emojis:
                # get the textual description
                description = self.emojis[token]
                text_no_emoji_lst.append(description)
            else:
                text_no_emoji_lst.append(token)
        text = u" ".join(x for x in text_no_emoji_lst)

        sentitext = SentiText(text)

        sentiments = []
        words_and_emoticons = sentitext.words_and_emoticons
        for item in words_and_emoticons:
            valence = 0
            i = words_and_emoticons.index(item)
            # check for vader_lexicon words that may be used as modifiers or negations
            if item.lower() in BOOSTER_DICT:
                sentiments.append(valence)
                continue
            if (i < len(words_and_emoticons) - 1 and item.lower() == u"kind" and
                    words_and_emoticons[i + 1].lower() == u"of"):
                sentiments.append(valence)
                continue

            sentiments = self.sentiment_valence(valence, sentitext, item, i, sentiments)

        sentiments = self._but_check(words_and_emoticons, sentiments)

        valence_dict = self.score_valence(sentiments, text)

        return valence_dict

    def sentiment_valence(self, valence, sentitext, item, i, sentiments):
        is_cap_diff = sentitext.is_cap_diff
        words_and_emoticons = sentitext.words_and_emoticons
        item_lowercase = item.lower()
        if item_lowercase in self.lexicon:
            # get the sentiment valence
            valence = self.lexicon[item_lowercase]
            # check if sentiment laden word is in ALL CAPS (while others aren't)
            if item.isupper() and is_cap_diff:
                if valence > 0:
                    valence += C_INCR
                else:
                    valence -= C_INCR

            for start_i in xrange(0, 3):
                # dampen the scalar modifier of preceding words and emoticons
                # (excluding the ones that immediately preceed the item) based
                # on their distance from the current item.
                if i > start_i and words_and_emoticons[i - (start_i + 1)].lower() not in self.lexicon:
                    s = scalar_inc_dec(words_and_emoticons[i - (start_i + 1)], valence, is_cap_diff)
                    if start_i == 1 and s != 0:
                        s = s * 0.95
                    if start_i == 2 and s != 0:
                        s = s * 0.9
                    valence = valence + s
                    valence = self._negation_check(valence, words_and_emoticons, start_i, i)
                    if start_i == 2:
                        valence = self._special_idioms_check(valence, words_and_emoticons, i)

            valence = self._least_check(valence, words_and_emoticons, i)
        sentiments.append(valence)
        return sentiments

    def _least_check(self, valence, words_and_emoticons, i):
        # check for negation case using "least"
        if i > 1 and words_and_emoticons[i - 1].lower() not in self.lexicon \
                and words_and_emoticons[i - 1].lower() == u"least":
            if words_and_emoticons[i - 2].lower() != u"at" and words_and_emoticons[i - 2].lower() != u"very":
                valence = valence * N_SCALAR
        elif i > 0 and words_and_emoticons[i - 1].lower() not in self.lexicon \
                and words_and_emoticons[i - 1].lower() == u"least":
            valence = valence * N_SCALAR
        return valence

    @staticmethod
    def _but_check(words_and_emoticons, sentiments):
        # check for modification in sentiment due to contrastive conjunction 'but'
        words_and_emoticons_lower = [unicode(w).lower() for w in words_and_emoticons]
        if u'but' in words_and_emoticons_lower:
            bi = words_and_emoticons_lower.index(u'but')
            for sentiment in sentiments:
                si = sentiments.index(sentiment)
                if si < bi:
                    sentiments.pop(si)
                    sentiments.insert(si, sentiment * 0.5)
                elif si > bi:
                    sentiments.pop(si)
                    sentiments.insert(si, sentiment * 1.5)
        return sentiments

    @staticmethod
    def _special_idioms_check(valence, words_and_emoticons, i):
        words_and_emoticons_lower = [unicode(w).lower() for w in words_and_emoticons]
        onezero = u"{0} {1}".format(words_and_emoticons_lower[i - 1], words_and_emoticons_lower[i])

        twoonezero = u"{0} {1} {2}".format(words_and_emoticons_lower[i - 2],
                                          words_and_emoticons_lower[i - 1], words_and_emoticons_lower[i])

        twoone = u"{0} {1}".format(words_and_emoticons_lower[i - 2], words_and_emoticons_lower[i - 1])

        threetwoone = u"{0} {1} {2}".format(words_and_emoticons_lower[i - 3],
                                           words_and_emoticons_lower[i - 2], words_and_emoticons_lower[i - 1])

        threetwo = u"{0} {1}".format(words_and_emoticons_lower[i - 3], words_and_emoticons_lower[i - 2])

        sequences = [onezero, twoonezero, twoone, threetwoone, threetwo]

        for seq in sequences:
            if seq in SPECIAL_CASE_IDIOMS:
                valence = SPECIAL_CASE_IDIOMS[seq]
                break

        if len(words_and_emoticons_lower) - 1 > i:
            zeroone = u"{0} {1}".format(words_and_emoticons_lower[i], words_and_emoticons_lower[i + 1])
            if zeroone in SPECIAL_CASE_IDIOMS:
                valence = SPECIAL_CASE_IDIOMS[zeroone]
        if len(words_and_emoticons_lower) - 1 > i + 1:
            zeroonetwo = u"{0} {1} {2}".format(words_and_emoticons_lower[i], words_and_emoticons_lower[i + 1],
                                              words_and_emoticons_lower[i + 2])
            if zeroonetwo in SPECIAL_CASE_IDIOMS:
                valence = SPECIAL_CASE_IDIOMS[zeroonetwo]

        # check for booster/dampener bi-grams such as 'sort of' or 'kind of'
        n_grams = [threetwoone, threetwo, twoone]
        for n_gram in n_grams:
            if n_gram in BOOSTER_DICT:
                valence = valence + BOOSTER_DICT[n_gram]
        return valence

    @staticmethod
    def _sentiment_laden_idioms_check(valence, senti_text_lower):
        # Future Work
        # check for sentiment laden idioms that don't contain a lexicon word
        idioms_valences = []
        for idiom in SENTIMENT_LADEN_IDIOMS:
            if idiom in senti_text_lower:
                print idiom, senti_text_lower
                valence = SENTIMENT_LADEN_IDIOMS[idiom]
                idioms_valences.append(valence)
        if len(idioms_valences) > 0:
            valence = sum(idioms_valences) / float(len(idioms_valences))
        return valence

    @staticmethod
    def _negation_check(valence, words_and_emoticons, start_i, i):
        words_and_emoticons_lower = [unicode(w).lower() for w in words_and_emoticons]
        if start_i == 0:
            if negated([words_and_emoticons_lower[i - (start_i + 1)]]):  # 1 word preceding lexicon word (w/o stopwords)
                valence = valence * N_SCALAR
        if start_i == 1:
            if words_and_emoticons_lower[i - 2] == u"never" and \
                    (words_and_emoticons_lower[i - 1] == u"so" or
                     words_and_emoticons_lower[i - 1] == u"this"):
                valence = valence * 1.25
            elif words_and_emoticons_lower[i - 2] == u"without" and \
                    words_and_emoticons_lower[i - 1] == u"doubt":
                valence = valence
            elif negated([words_and_emoticons_lower[i - (start_i + 1)]]):  # 2 words preceding the lexicon word position
                valence = valence * N_SCALAR
        if start_i == 2:
            if words_and_emoticons_lower[i - 3] == u"never" and \
                    (words_and_emoticons_lower[i - 2] == u"so" or words_and_emoticons_lower[i - 2] == u"this") or \
                    (words_and_emoticons_lower[i - 1] == u"so" or words_and_emoticons_lower[i - 1] == u"this"):
                valence = valence * 1.25
            elif words_and_emoticons_lower[i - 3] == u"without" and \
                    (words_and_emoticons_lower[i - 2] == u"doubt" or words_and_emoticons_lower[i - 1] == u"doubt"):
                valence = valence
            elif negated([words_and_emoticons_lower[i - (start_i + 1)]]):  # 3 words preceding the lexicon word position
                valence = valence * N_SCALAR
        return valence

    def _punctuation_emphasis(self, text):
        # add emphasis from exclamation points and question marks
        ep_amplifier = self._amplify_ep(text)
        qm_amplifier = self._amplify_qm(text)
        punct_emph_amplifier = ep_amplifier + qm_amplifier
        return punct_emph_amplifier

    @staticmethod
    def _amplify_ep(text):
        # check for added emphasis resulting from exclamation points (up to 4 of them)
        ep_count = text.count(u"!")
        if ep_count > 4:
            ep_count = 4
        # (empirically derived mean sentiment intensity rating increase for
        # exclamation points)
        ep_amplifier = ep_count * 0.292
        return ep_amplifier

    @staticmethod
    def _amplify_qm(text):
        # check for added emphasis resulting from question marks (2 or 3+)
        qm_count = text.count(u"?")
        qm_amplifier = 0
        if qm_count > 1:
            if qm_count <= 3:
                # (empirically derived mean sentiment intensity rating increase for
                # question marks)
                qm_amplifier = qm_count * 0.18
            else:
                qm_amplifier = 0.96
        return qm_amplifier

    @staticmethod
    def _sift_sentiment_scores(sentiments):
        # want separate positive versus negative sentiment scores
        pos_sum = 0.0
        neg_sum = 0.0
        neu_count = 0
        for sentiment_score in sentiments:
            if sentiment_score > 0:
                pos_sum += (float(sentiment_score) + 1)  # compensates for neutral words that are counted as 1
            if sentiment_score < 0:
                neg_sum += (float(sentiment_score) - 1)  # when used with math.fabs(), compensates for neutrals
            if sentiment_score == 0:
                neu_count += 1
        return pos_sum, neg_sum, neu_count

    def score_valence(self, sentiments, text):
        if sentiments:
            sum_s = float(sum(sentiments))
            # compute and add emphasis from punctuation in text
            punct_emph_amplifier = self._punctuation_emphasis(text)
            if sum_s > 0:
                sum_s += punct_emph_amplifier
            elif sum_s < 0:
                sum_s -= punct_emph_amplifier

            compound = normalize(sum_s)
            # discriminate between positive, negative and neutral sentiment scores
            pos_sum, neg_sum, neu_count = self._sift_sentiment_scores(sentiments)

            if pos_sum > math.fabs(neg_sum):
                pos_sum += punct_emph_amplifier
            elif pos_sum < math.fabs(neg_sum):
                neg_sum -= punct_emph_amplifier

            total = pos_sum + math.fabs(neg_sum) + neu_count
            pos = math.fabs(pos_sum / total)
            neg = math.fabs(neg_sum / total)
            neu = math.fabs(neu_count / total)

        else:
            compound = 0.0
            pos = 0.0
            neg = 0.0
            neu = 0.0

        sentiment_dict = \
            {u"neg": round(neg, 3),
             u"neu": round(neu, 3),
             u"pos": round(pos, 3),
             u"compound": round(compound, 4)}

        return sentiment_dict


if __name__ == u'__main__':
    # --- examples -------
    sentences = [u"VADER is smart, handsome, and funny.",  # positive sentence example
                 u"VADER is smart, handsome, and funny!",
                 # punctuation emphasis handled correctly (sentiment intensity adjusted)
                 u"VADER is very smart, handsome, and funny.",
                 # booster words handled correctly (sentiment intensity adjusted)
                 u"VADER is VERY SMART, handsome, and FUNNY.",  # emphasis for ALLCAPS handled
                 u"VADER is VERY SMART, handsome, and FUNNY!!!",
                 # combination of signals - VADER appropriately adjusts intensity
                 u"VADER is VERY SMART, uber handsome, and FRIGGIN FUNNY!!!",
                 # booster words & punctuation make this close to ceiling for score
                 u"VADER is not smart, handsome, nor funny.",  # negation sentence example
                 u"The book was good.",  # positive sentence
                 u"At least it isn't a horrible book.",  # negated negative sentence with contraction
                 u"The book was only kind of good.",
                 # qualified positive sentence is handled correctly (intensity adjusted)
                 u"The plot was good, but the characters are uncompelling and the dialog is not great.",
                 # mixed negation sentence
                 u"Today SUX!",  # negative slang with capitalization emphasis
                 u"Today only kinda sux! But I'll get by, lol",
                 # mixed sentiment example with slang and constrastive conjunction "but"
                 u"Make sure you :) or :D today!",  # emoticons handled
                 u"Catch utf-8 emoji such as 💘 and 💋 and 😁",  # emojis handled
                 u"Not bad at all"  # Capitalized negation
                 ]

    analyzer = SentimentIntensityAnalyzer()

    print u"----------------------------------------------------"
    print u" - Analyze typical example cases, including handling of:"
    print u"  -- negations"
    print u"  -- punctuation emphasis & punctuation flooding"
    print u"  -- word-shape as emphasis (capitalization difference)"
    print u"  -- degree modifiers (intensifiers such as 'very' and dampeners such as 'kind of')"
    print u"  -- slang words as modifiers such as 'uber' or 'friggin' or 'kinda'"
    print u"  -- contrastive conjunction 'but' indicating a shift in sentiment; sentiment of later text is dominant"
    print u"  -- use of contractions as negations"
    print u"  -- sentiment laden emoticons such as :) and :D"
    print u"  -- utf-8 encoded emojis such as 💘 and 💋 and 😁"
    print u"  -- sentiment laden slang words (e.g., 'sux')"
    print u"  -- sentiment laden initialisms and acronyms (for example: 'lol') \n"
    for sentence in sentences:
        vs = analyzer.polarity_scores(sentence)
        print u"{:-<65} {}".format(sentence, unicode(vs))
    print u"----------------------------------------------------"
    print u" - About the scoring: "
    print u"""  -- The 'compound' score is computed by summing the valence scores of each word in the lexicon, adjusted
     according to the rules, and then normalized to be between -1 (most extreme negative) and +1 (most extreme positive).
     This is the most useful metric if you want a single unidimensional measure of sentiment for a given sentence.
     Calling it a 'normalized, weighted composite score' is accurate."""
    print u"""  -- The 'pos', 'neu', and 'neg' scores are ratios for proportions of text that fall in each category (so these
     should all add up to be 1... or close to it with float operation).  These are the most useful metrics if
     you want multidimensional measures of sentiment for a given sentence."""
    print u"----------------------------------------------------"

    # input("\nPress Enter to continue the demo...\n")  # for DEMO purposes...

    tricky_sentences = [u"Sentiment analysis has never been good.",
                        u"Sentiment analysis has never been this good!",
                        u"Most automated sentiment analysis tools are shit.",
                        u"With VADER, sentiment analysis is the shit!",
                        u"Other sentiment analysis tools can be quite bad.",
                        u"On the other hand, VADER is quite bad ass",
                        u"VADER is such a badass!",  # slang with punctuation emphasis
                        u"Without a doubt, excellent idea.",
                        u"Roger Dodger is one of the most compelling variations on this theme.",
                        u"Roger Dodger is at least compelling as a variation on the theme.",
                        u"Roger Dodger is one of the least compelling variations on this theme.",
                        u"Not such a badass after all.",  # Capitalized negation with slang
                        u"Without a doubt, an excellent idea."  # "without {any} doubt" as negation
                        ]
    print u"----------------------------------------------------"
    print u" - Analyze examples of tricky sentences that cause trouble to other sentiment analysis tools."
    print u"  -- special case idioms - e.g., 'never good' vs 'never this good', or 'bad' vs 'bad ass'."
    print u"  -- special uses of 'least' as negation versus comparison \n"
    for sentence in tricky_sentences:
        vs = analyzer.polarity_scores(sentence)
        print u"{:-<69} {}".format(sentence, unicode(vs))
    print u"----------------------------------------------------"

    # input("\nPress Enter to continue the demo...\n")  # for DEMO purposes...

    print u"----------------------------------------------------"
    print u" - VADER works best when analysis is done at the sentence level (but it can work on single words or entire novels)."
    paragraph = u"It was one of the worst movies I've seen, despite good reviews. Unbelievably bad acting!! Poor direction. VERY poor production. The movie was bad. Very bad movie. VERY BAD movie!"
    print u"  -- For example, given the following paragraph text from a hypothetical movie review:\n\t'{}'".format(
        paragraph)
    print u"  -- You could use NLTK to break the paragraph into sentence tokens for VADER, then average the results for the paragraph like this: \n"
    # simple example to tokenize paragraph into sentences for VADER
    from nltk import tokenize

    sentence_list = tokenize.sent_tokenize(paragraph)
    paragraphSentiments = 0.0
    for sentence in sentence_list:
        vs = analyzer.polarity_scores(sentence)
        print u"{:-<69} {}".format(sentence, unicode(vs[u"compound"]))
        paragraphSentiments += vs[u"compound"]
    print u"AVERAGE SENTIMENT FOR PARAGRAPH: \t" + unicode(round(paragraphSentiments / len(sentence_list), 4))
    print u"----------------------------------------------------"

    # input("\nPress Enter to continue the demo...\n")  # for DEMO purposes...

    print u"----------------------------------------------------"
    print u" - Analyze sentiment of IMAGES/VIDEO data based on annotation 'tags' or image labels. \n"
    conceptList = [u"balloons", u"cake", u"candles", u"happy birthday", u"friends", u"laughing", u"smiling", u"party"]
    conceptSentiments = 0.0
    for concept in conceptList:
        vs = analyzer.polarity_scores(concept)
        print u"{:-<15} {}".format(concept, unicode(vs[u'compound']))
        conceptSentiments += vs[u"compound"]
    print u"AVERAGE SENTIMENT OF TAGS/LABELS: \t" + unicode(round(conceptSentiments / len(conceptList), 4))
    print u"\t"
    conceptList = [u"riot", u"fire", u"fight", u"blood", u"mob", u"war", u"police", u"tear gas"]
    conceptSentiments = 0.0
    for concept in conceptList:
        vs = analyzer.polarity_scores(concept)
        print u"{:-<15} {}".format(concept, unicode(vs[u'compound']))
        conceptSentiments += vs[u"compound"]
    print u"AVERAGE SENTIMENT OF TAGS/LABELS: \t" + unicode(round(conceptSentiments / len(conceptList), 4))
    print u"----------------------------------------------------"

    # input("\nPress Enter to continue the demo...")  # for DEMO purposes...

    do_translate = raw_input(
        u"\nWould you like to run VADER demo examples with NON-ENGLISH text? (Note: requires Internet access) \n Type 'y' or 'n', then press Enter: ")
    if do_translate.lower().lstrip().__contains__(u"y"):
        print u"\n----------------------------------------------------"
        print u" - Analyze sentiment of NON ENGLISH text...for example:"
        print u"  -- French, German, Spanish, Italian, Russian, Japanese, Arabic, Chinese"
        print u"  -- many other languages supported. \n"
        languages = [u"English", u"French", u"German", u"Spanish", u"Italian", u"Russian", u"Japanese", u"Arabic", u"Chinese"]
        language_codes = [u"en", u"fr", u"de", u"es", u"it", u"ru", u"ja", u"ar", u"zh"]
        nonEnglish_sentences = [u"I'm surprised to see just how amazingly helpful VADER is!",
                                u"Je suis surpris de voir juste comment incroyablement utile VADER est!",
                                u"Ich bin überrascht zu sehen, nur wie erstaunlich nützlich VADER!",
                                u"Me sorprende ver sólo cómo increíblemente útil VADER!",
                                u"Sono sorpreso di vedere solo come incredibilmente utile VADER è!",
                                u"Я удивлен увидеть, как раз как удивительно полезно ВЕЙДЕРА!",
                                u"私はちょうどどのように驚くほど役に立つベイダーを見て驚いています!",
                                u"أنا مندهش لرؤية فقط كيف مثير للدهشة فيدر فائدة!",
                                u"惊讶地看到有用维德是的只是如何令人惊讶了 ！"
                                ]
        for sentence in nonEnglish_sentences:
            to_lang = u"en"
            from_lang = language_codes[nonEnglish_sentences.index(sentence)]
            if (from_lang == u"en") or (from_lang == u"en-US"):
                translation = sentence
                translator_name = u"No translation needed"
            else:  # please note usage limits for My Memory Translation Service:   http://mymemory.translated.net/doc/usagelimits.php
                # using   MY MEMORY NET   http://mymemory.translated.net
                api_url = u"http://mymemory.translated.net/api/get?q={}&langpair={}|{}".format(sentence, from_lang,
                                                                                              to_lang)
                hdrs = {
                    u'User-Agent': u'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.11 (KHTML, like Gecko) Chrome/23.0.1271.64 Safari/537.11',
                    u'Accept': u'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    u'Accept-Charset': u'ISO-8859-1,utf-8;q=0.7,*;q=0.3',
                    u'Accept-Encoding': u'none',
                    u'Accept-Language': u'en-US,en;q=0.8',
                    u'Connection': u'keep-alive'}
                response = requests.get(api_url, headers=hdrs)
                response_json = json.loads(response.text)
                translation = response_json[u"responseData"][u"translatedText"]
                translator_name = u"MemoryNet Translation Service"
            vs = analyzer.polarity_scores(translation)
            print u"- {: <8}: {: <69}\t {} ({})".format(languages[nonEnglish_sentences.index(sentence)], sentence,
                                                       unicode(vs[u'compound']), translator_name)
        print u"----------------------------------------------------"

    print u"\n\n Demo Done!"
