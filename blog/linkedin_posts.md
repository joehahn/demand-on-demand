# LinkedIn series (drafts)

Four posts, about a week apart. Each links to the live demo; the last line points to jmh-datasciences.com.
Suggested image for each is noted.

---

## Post 1: the demo

I typed "monthly forecast of Tito's minis in Des Moines for the next 5 months" and got this back 30 seconds later.

Behind it: a Claude agent that turns plain English into a precise request against a database of 26 million Iowa
liquor orders, and a fixed Python pipeline that trains, tunes and tests the forecast before anyone sees it.

The agent handles the tedious part: finding the right products (Tito's has 11 item numbers), the right place, the
right measure and horizon. It does not write the SQL, pick the test data, or grade itself. That part is fixed code,
the same for every request.

Each forecast comes with one plain sentence on how far to trust it, measured on 24 months the model never saw.

Cost per request: about two cents.

Live demo and code: https://joehahn.github.io/demand-on-demand/

*Image: the top of the Des Moines dashboard.*

---

## Post 2: the first bug was in the state's export

Before forecasting anything, I profiled ten years of Iowa's public liquor sales data. Things I found:

- 1.5 million rows duplicated in the state's own download. Left in, 2022 looks 23% bigger than it was.
- A category code that meant "Bottled in Bond Bourbon" one week and "Tennessee Whiskies" the next.
- A whole category that "disappeared" in 2022. It had moved to a new code.
- 254 products renumbered mid-history.

An AI agent can be taught to catch these on every request. I tried it, and it worked. Then I moved the fixes into
the database, once, where they belong. Every forecast since is faster, cheaper and consistent.

Before and after for every fix: https://joehahn.github.io/demand-on-demand/data_fixes.html

*Image: the Tennessee whiskey before/after chart.*

---

## Post 3: where I let the AI decide, and where I didn't

The rule I build AI systems by: the AI decides what to do; fixed code decides how.

In my forecasting demo, a Claude agent reads "what revenue should we expect from Fireball in Linn County next
quarter?" and resolves it: the Fireball products, Linn County, dollars, 3 months. Then it stops.

It never writes the query, chooses the test data, computes the accuracy, or draws the charts. Those are the steps
where a forecast earns trust, so they are ordinary code, identical every time, that I can test.

The agent's database login is read-only. Its credentials never enter a prompt. The summary it writes may only quote
numbers the pipeline computed, and a check confirms that.

On 19 test requests run twice each, including ones it should refuse, it got all 38 right.

https://github.com/joehahn/demand-on-demand

*Image: the "How it works" diagram from the landing page.*

---

## Post 4: it beat last year on 21 of 30. Here are the other 9.

Every forecast in my demo is compared with the simplest honest benchmark: "the same month last year."

For Iowa liquor, that benchmark is hard to beat. October is the peak every year, December is low because stores
stocked up already, and recent years look alike.

On 30 sampled forecasts, the model beat it 21 times, with a median error 8% lower. On 9 it did not, including Irish
whiskey statewide.

I publish all 30, because a forecast you can't check isn't worth much. The pipeline only lets a model take over as
far as it beats last year on months it never saw, and each dashboard says which case you're in.

If your business runs on forecasts someone still builds by hand, let's talk: https://jmh-datasciences.com

*Image: the benchmark table.*
