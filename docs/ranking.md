# How ranking works

Every list of stories goes through `rank()` in `app/rank.py`. A tab sorts its stories one of two ways:

- **Latest**: newest first. Stories you hid are left out.
- **Recommended**: scored from what you opened, liked and hid, and how old each story is. Described below.

History is always chronological and is never ranked.

## The signals

Each story gets five signals, each from 0 to 1.

| Signal | Dial | What it measures |
|---|---|---|
| `like` | Like what you open | Of the 5 stories you rated that are most like it, the share you opened or liked rather than hid |
| `source` | (part of Like) | How stories from its source went: opened or liked, or hidden |
| `popular` | Popular | Points and comments, compared with other stories from the same source |
| `random` | Surprise | A dice roll per story that stays the same all day |
| `fresh` | Fresh | How recently it was published |

**The vote** (`like`) uses the story embeddings (EmbeddingGemma, run locally). The 5 stories you rated (opened,
liked or hid) that are most like a story each vote on it: a like for, a hide against. The Unlike dial sets how much
a hide counts: at 0.5 as much as a like, at 1 twice as much, at 0 not at all. One vote for and one against are
added to every count, so a story with nothing rated near it, or no vector yet, sits at a neutral 0.5, and a single
vote doesn't swing it all the way.

**Source** is the same idea by source instead of by meaning: how often you liked rather than hid stories from it.
Until a source has a few ratings, it leans on how its medium went. Some tastes are about form (essays, papers)
more than topic, and embeddings mostly see topic.

**Popularity** is also a percentile, but within each source, because 300 points on Hacker News and 30 on Lobsters
mean about the same. Sources without points or comments are a neutral 0.5.

**Freshness** halves every *half-life* of the story's medium, set as `half_life_days` in `catalog/tags.json`:

| Medium | Half-life | Stays on the homepage |
|---|---|---|
| News | 5 days | 3 days |
| Forums | 5 days | 7 days |
| Papers | 15 days | 14 days |
| Blogs | 20 days | 60 days |

Half-lives longer than a story's time on the homepage are on purpose: age breaks ties between stories you'd like
about equally. It doesn't bury a good one from two days ago.

## The score

```
wanted = (0.75·like + 0.25·source)·w_like + popular·w_popular + 0.2·random·w_random
score  = wanted × fresh^(2·w_fresh)
```

Each part plays a different role:

- **What you'd want**: relevance and popularity add up. What you hid counts inside relevance, through the vote.
- **Time multiplies everything.** At Fresh 0.5, a story loses half its score every half-life. At 1 it fades twice
  as fast, and at 0 age doesn't count at all. Because time multiplies, an old story has to be much more relevant
  than a new one to beat it.
- **Chance only breaks near-ties.** It counts for at most a fifth of what Like does, so stories you'd rank about
  equally are mixed up a little each day without the dice deciding the page.

Equal scores stay newest first.

## Where the weights come from

The dials in Settings are the weights, from 0 to 1, in steps of 0.1. In onboarding, `learn()` sets the Like,
Unlike, Fresh and Popular weights from your ratings:

1. Each weight starts at 0.5.
2. It moves by how much more of its signal the stories you liked had than the ones you didn't. For example,
   liking only fresh stories turns Fresh up.
3. With only a few ratings it moves less: after 5 ratings, it moves half as far as the ratings suggest.

Surprise is never learned, because clicks would always turn it down. After onboarding, the dials are yours.

## Choices, and what we left out

These were trade-offs, so here's what we picked and what we passed on:

- **Time multiplies; it isn't one more signal added on top.** When freshness was added like the other signals, a
  barely relevant story could reach the top on age and luck alone.
- **Freshness counts real age, not a share of the time on the homepage.** Blogs stay on the homepage for 60 days,
  so with the old share-of-time version a two-week-old post still counted as fairly fresh.
- **We don't take the top N by relevance and then sort by time.** That ranks predictably, but there's a hard edge:
  story N+1 never shows, however new it is. It could come back as an option for a single tab.
- **A vote, not the nearest like.** Recommended used to score a story by how close it was to the nearest story you
  liked, within its own topics, with hides as a separate penalty. Once you've liked a few papers, every paper is
  near one, so that saturated. Not every paper's neighbours are ones you liked, so a vote doesn't. And a hide
  next to your likes now counts against them directly, instead of taking a second bite out of the score.
- **The dials stop learning after onboarding.** Your taste keeps learning anyway: the vote is worked out again
  from all your opens, likes and hides on every page load. Learning the dials from homepage clicks would mostly
  learn the ranking back: you click what is shown, and what's at the top, so Fresh would keep turning itself up.
  Onboarding ratings don't have that problem, because the sample isn't ranked. And dials that move on their own
  are no longer yours to set. A later option: suggest a change in Settings and let you apply it.
- **Tuned on simulated readers, not real ones.** See below.

## How we measured it

There are no real users to replay yet, so we made five: a daily news skimmer, a paper reader, a reader of long
blog essays, a forum hunter who goes by points and comments, and a security specialist. An LLM played each one and
rated 300 stories from the homepage (a random sample of 1,123) from 0 (would hide) to 3 (must read), seeing each
story's age. A script then plays onboarding with those ratings (a spread of 5, then 3 rounds of the 5 best
matches so far, then `learn()`), and a week of homepage use (opening the liked stories in the top 20). After each
stage it scores Recommended on the stories not rated yet, by NDCG@20. We tuned on three readers and kept the forum
hunter and the security specialist apart to check the result. Mean NDCG@20 at the default dials, over 20 runs
each:

| | Tuning readers | Held-out readers |
|---|---|---|
| Before | 0.19 | 0.17 |
| After | 0.40 | 0.50 |

What made the difference, biggest first:
- The vote instead of the nearest like.
- Freshness 5 times weaker. On its own, age predicted almost nothing of what even the skimmer wanted.
- Popularity learned from ratings at all: onboarding shows one story per source, so among the rated stories alone
  each was the only one from its source and always 0.5.
- The source signal.

LLM readers are tidier than people, so this shows the ranking can follow these kinds of taste, not that real users
are happier. The sample is also mostly older than two days (the homepage keeps blogs for 60), so freshness is the
least certain part.
