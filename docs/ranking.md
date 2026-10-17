# How ranking works

Every list of stories goes through `rank()` in `app/rank.py`. A tab sorts its stories one of two ways:

- **Latest**: newest first. Stories you hid are left out.
- **Recommended**: scored from what you opened, liked and hid, and how old each story is. Described below.

History is always chronological and is never ranked.

## The signals

Each story gets five signals, each from 0 to 1.

| Signal | Dial | What it measures |
|---|---|---|
| `like` | Like what you open | How close the story is to the nearest story you opened or liked |
| `hidden` | Unlike what you hide | How close the story is to the nearest story you hid |
| `popular` | Popular | Points and comments, compared with other stories from the same source |
| `random` | Surprise | A dice roll per story that stays the same all day |
| `fresh` | Fresh | How recently it was published |

**Closeness** (`like`, `hidden`) uses the story embeddings (EmbeddingGemma, run locally). It is worked out per topic:
a story is compared only with the stories you rated in its own topics. Liking AI stories lifts AI without sinking
politics, and a topic you haven't rated yet stays at a neutral 0.5. Sources without topics (Hacker News, Lobsters)
are compared with everything. Raw similarities sit in a narrow band, so they're turned into percentiles: 1 is the
closest story in the pool, 0 the furthest.

**Popularity** is also a percentile, but within each source, because 300 points on Hacker News and 30 on Lobsters
mean about the same. Sources without points or comments are a neutral 0.5.

**Freshness** halves every *half-life* of the story's medium, set as `half_life_days` in `catalog/tags.json`:

| Medium | Half-life | Stays on the homepage |
|---|---|---|
| News | 1 day | 3 days |
| Forums | 1 day | 7 days |
| Papers | 3 days | 14 days |
| Blogs | 4 days | 60 days |

## The score

```
wanted = like·w_like + popular·w_popular + 0.2·random·w_random
score  = wanted × (1 − hidden·w_hidden) × fresh^(2·w_fresh)
```

Each part plays a different role:

- **What you'd want**: relevance and popularity add up.
- **What you wouldn't**: a look-alike of something you hid loses up to `w_hidden` of its score. At Unlike 1, a
  story right next to one you hid drops to zero.
- **Time multiplies everything.** At Fresh 0.5, a story loses half its score every half-life. At 1 it fades twice
  as fast, and at 0 age doesn't count at all. Because time multiplies, an old story has to be much more relevant
  than a new one to beat it, but a very relevant story can still stay up for a while.
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
- **The dials stop learning after onboarding.** Your taste keeps learning anyway: closeness is worked out again
  from all your opens, likes and hides on every page load. Learning the dials from homepage clicks would mostly
  learn the ranking back: you click what is shown, and what's at the top, so Fresh would keep turning itself up.
  Onboarding ratings don't have that problem, because the sample isn't ranked. And dials that move on their own
  are no longer yours to set. A later option: suggest a change in Settings and let you apply it.
- **There's no offline evaluation yet.** Replaying the history of real users would show whether a change helps. For
  now the weights and half-lives are reasonable defaults, not tuned ones.
