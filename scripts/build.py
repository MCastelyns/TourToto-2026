"""Runs scoring.py then generate_site.py in order. Call this after dropping
new data/results/stage_NN.json (or final.json) files in place."""
import scoring
import generate_site

if __name__ == "__main__":
    scoring.main()
    print()
    generate_site.main()
