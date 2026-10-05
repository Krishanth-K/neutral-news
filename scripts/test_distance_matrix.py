"""
Script to test and print pairwise distance matrices between two articles.
Demonstrates:
- Semantic Embedding distance (Cosine)
- Temporal distance (Publication time delta in hours)
- Named Entity distance (Jaccard)
- Full 2x2 Distance Matrix
"""

import sys
import psycopg
import numpy as np

from neutral_news.config import DATABASE_URL
from neutral_news.embed.distance import compute_distance_between_two_articles


def print_test_case(test_num: int, title: str, res: dict):
    art_a = res["article_a"]
    art_b = res["article_b"]

    print("=" * 80)
    print(f" TEST {test_num}: {title.upper()}")
    print("=" * 80)
    print(f"Article A ({art_a['source']}):")
    print(f"  ID:        {art_a['id']}")
    print(f"  Headline:  {art_a['headline']}")
    print(f"  Published: {art_a['published_at']}")
    print()
    print(f"Article B ({art_b['source']}):")
    print(f"  ID:        {art_b['id']}")
    print(f"  Headline:  {art_b['headline']}")
    print(f"  Published: {art_b['published_at']}")
    print()
    print("-" * 80)
    print(" METRICS BREAKDOWN")
    print("-" * 80)
    print(f"  • Cosine Similarity:      {res['cosine_similarity']:.4f}")
    print(f"  • Embedding Distance:     {res['embedding_distance']:.4f}  (weight: {res['weights']['embedding']})")
    print(f"  • Time Difference:        {res['time_distance_hours']:.2f} hours → normalised: {res['time_distance_normalised']:.4f}  (weight: {res['weights']['time']})")
    
    shared_named = [t[0] for t in sorted(res["shared_entities"])]
    print(f"  • Named Entity Distance:  {res['entity_distance']:.4f}  (weight: {res['weights']['entity']})")
    print(f"    - Entities in A: {len(res['entities_a'])}, Entities in B: {len(res['entities_b'])}")
    print(f"    - Shared Entities ({len(shared_named)}): {', '.join(shared_named[:8]) if shared_named else 'None'}")
    print()
    weighted_emb = res['weights']['embedding'] * res['embedding_distance']
    weighted_time = res['weights']['time'] * res['time_distance_normalised']
    weighted_ent = res['weights']['entity'] * res['entity_distance']
    print(f"  • Formula: 0.55 * ({res['embedding_distance']:.4f}) + 0.25 * ({res['time_distance_normalised']:.4f}) + 0.20 * ({res['entity_distance']:.4f})")
    print(f"           = {weighted_emb:.4f} + {weighted_time:.4f} + {weighted_ent:.4f}")
    print(f"  • Total Pairwise Distance: {res['total_distance']:.4f}")
    print()
    print("-" * 80)
    print(" 2x2 DISTANCE MATRIX")
    print("-" * 80)
    
    labels = [f"Art A ({art_a['source'][:8]})", f"Art B ({art_b['source'][:8]})"]
    matrix = res["matrix"]
    
    print(f"                  {labels[0]:<20} {labels[1]:<20}")
    print(f"{labels[0]:<17} [ {matrix[0, 0]:>10.4f}         {matrix[0, 1]:>10.4f}         ]")
    print(f"{labels[1]:<17} [ {matrix[1, 0]:>10.4f}         {matrix[1, 1]:>10.4f}         ]")
    print()


def run_tests():
    test_cases = [
        {
            "title": "Self-Comparison / Identical Article (Zero Distance Baseline)",
            "id_a": "b6cad841-2ff9-414e-a13c-af2a287073a0",
            "id_b": "b6cad841-2ff9-414e-a13c-af2a287073a0",
        },
        {
            "title": "Same Breaking News Across Outlets (Times of India vs Indian Express)",
            "id_a": "b6cad841-2ff9-414e-a13c-af2a287073a0", # Pocso escape (TOI)
            "id_b": "5ea7edc7-c939-43b7-adea-6c3c242159ee", # Pocso escape (IE)
        },
        {
            "title": "Same Story Across Outlets (The Hindu vs Indian Express - Odisha Shipwreck)",
            "id_a": "c1ccb93f-dbf0-42f4-bfd5-abc3144c4be8", # Ship sinks off Odisha (The Hindu)
            "id_b": "f8d483e9-8238-4f83-a274-e56534ed7c04", # Ship sinking survivors (IE)
        },
        {
            "title": "Same Broad Domain, Different Specific News (Elections / Party Strategy)",
            "id_a": "d1fb4e99-7fb9-4545-89aa-16b8d0257fb0", # BJP chief strategy meet (The Hindu)
            "id_b": "06b15673-ebd1-40ea-bd2b-7c23cda625c5", # BJP poll strategy for 7 states (TOI)
        },
        {
            "title": "Completely Unrelated Topics (Political Posters vs Commodity Prices)",
            "id_a": "a4057bc2-072d-4399-a11e-0fcb664001de", # Rahul Gandhi Batman poster (The Hindu)
            "id_b": "c0a6b9a3-c96b-43ab-887d-f958e1b8feb0", # Sugar price hike (The Hindu)
        },
        {
            "title": "Long Time Delta Test (~27 Days Apart, Different Topics)",
            "id_a": "b6cad841-2ff9-414e-a13c-af2a287073a0", # Pocso escape (TOI, Aug 23)
            "id_b": "a3b6d397-9a79-4f32-a346-17f7d3215f3f", # CJP politics (IE, Jul 27)
        },
    ]

    with psycopg.connect(DATABASE_URL) as conn:
        for idx, tc in enumerate(test_cases, 1):
            res = compute_distance_between_two_articles(tc["id_a"], tc["id_b"], conn)
            print_test_case(idx, tc["title"], res)


if __name__ == "__main__":
    run_tests()
