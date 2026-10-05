Currently the clustering is not working as intended:
completely unrelated articles are being grouped together


issues:
- embedding is the main issue. un-similar articles get a low distance score instead of high

- fix: 
    - reduce the weightage of embedding distance, and increase the weight of ner distance
    - reduce hac clustering threshold (from 0.4 to 0.33)
    - future: choose a better embedding model
    <!-- - add a hard gate for ner -->


After parameter tuning:
    distance_threshold = 0.33   (was 0.40)
    weight_embedding   = 0.55   (unchanged)
    weight_time        = 0.30   (was 0.25)
    weight_entity      = 0.15   (was 0.20)

- 32 articles were selected from the busiest day (2026-08-14, 144 total)
- Those 32 articles were grouped into 10 same-event clusters by reading the headlines (not 100 events)
- The script auto-derived 76 labeled pairs from those groups: 19 positive (same event) + 57 negative (different events)
- Grid search ran over 369 parameter combos evaluated against those 76 pairs

refer run_tune_auto.py for more info
