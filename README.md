# hajime
Building a 2d Simulation Judo game

## Start Here

Yerrrr

Read the hajime-orientation file to understand what we are building with HAJIME (working titile)

The hajime-master-doc contains the roadmap. Features are also planned here. 

The Design Notes gets into the nitty gritty of the planned systems

## Local setup

After cloning, enable the pre-commit hook so the technique catalog is validated on every commit that touches it:

```
git config core.hooksPath .githooks
```

The hook runs `src/catalog_validator.py` against `data/techniques.yaml` whenever the catalog, the validator, or the loader is staged. Validator errors abort the commit; warnings and infos are non-blocking. Run the full report manually with `python src/catalog_validator.py data/techniques.yaml`.

*Forever Onwards, Comrades!*
