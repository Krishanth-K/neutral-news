## Event grouping

Using 4 criteria to group events:
- Embedding score
- Time-frame similarity
- Named Entity similarity
- Source outlet (de-duping)

### Clustering methods considered:

#### Single pass / threshold based:

> If the *distance of new datapoint and the centroid of existing cluster* < threshold => add to the cluster ; else start a new cluster

But the order of datapoints matter. In this case, two similar articles coming in different order could be grouped in seperate clusters. => **Order dependency flaw**


#### Graph based:

> Build a graph of datapoints. Two points are connected if their *similarity < threshold*. Connected points belong to a cluster

This produces **Chaining flaw**.
A -> B -> C might be connected as (A, B) are similar, and (B, C) are similar. But (A, C) might not be.

Ex:
  A₁ ──── A₂ ──── A₃
 (farmers  (farm  (trade
  protest)  subsidies) war)


#### Hierarchial Agglomerative Clustering (HAC):

> Start with every node as its own cluster. At every step merge the most similar clusters. Stop when merging two clusters would require crossing a similarity threshold.

    Step 0:  [A₁] [A₂] [A₃] [A₄] [A₅]   (everyone alone)
    Step 1:  [A₁,A₂]  [A₃] [A₄] [A₅]    (A₁ and A₂ are closest → merge)
    Step 2:  [A₁,A₂]  [A₃,A₄] [A₅]      (next closest pair merges)
    Step 3:  STOP — merging [A₁,A₂] with [A₃,A₄] would require crossing
                    a similarity threshold we set as the cutoff.


The linkage rule (how you measure distance between two groups) determines if chaining happens:

• Single linkage → distance = closest pair between groups → chains badly
• Complete linkage → distance = farthest pair between groups → avoids chains, creates tight compact clusters
• Average linkage → distance = average of all pairs → balanced

HAC with *complete linkage solves the chaining problem* because to merge two clusters, every point in cluster A must be close enough to every point in cluster B. Not just one bridge point.

This is the most principled method. The downside is it needs all articles at once (batch), and it's *O(N²) or O(N³)* in complexity.


#### 4. HDBSCAN (Density-Based)

> "A cluster is a dense region of space, separated from other dense regions by a sparse gap. Isolated outlier points are noise, not clusters."


  ● ●         ●●●●         ●   ← isolated article (noise / outlier)
 ●●●●   ←gap→ ●●●●
 ●●●           ●●

 Event 1      Event 2    (noise)

explicitly handles the "one-off" article that doesn't belong to any event —> marked as noise
HAC and threshold methods would `force-assign` it somewhere.

The weakness: the time-window constraint is tricky to inject cleanly. Also, in 768-dimensional embedding space, "density" becomes increasingly hard to define reliably — this is the curse of dimensionality problem.
