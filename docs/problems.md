1. What clustering method to choose??
    Currently going with HAC with average linking

---

2. How to calculate a distance score with the 3 criteria??
    Choosing a weighted sum for now.
    Need to think of a "dynamic" method, to use a wider/shorter timeframe based on the article

---

3. How to distinguish between on-going events vs new events??

        Day 1:  "Wayanad landslide kills 80, rescue underway"
        Day 3:  "Wayanad rescue: 200 more survivors found, Army deployed"
        Day 7:  "Wayanad death toll rises to 400, PM visits site"
        Day 14: "Wayanad relief funds: Centre releases ₹500 crore"
        Day 30: "Wayanad rebuilding plan announced"

    what about multiple articles on a same event over a week? it could be about a disaster - rescue missons which could take weeks, and the would be similar as well. so we cant just use a hardcoded filter.

---

4. Use a non-linear distance calculation for time distance
