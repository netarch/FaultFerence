## Requirements:
    - GCC 8 or above
    - Google sparsehash. To install
```
git clone https://github.com/sparsehash/sparsehash 
cd sparsehash; ./configure --prefix=`pwd`
make -j8
make install
```

## Compilation
From the top-level directory, run the following commands,
```
make clean; make -j8
cd faultference; make clean; make -j8
```

## Running
From the top-level directory, run the following commands,
```
cd faultference; bash ./sweep_inferences_sequences.sh
```
Parameters can be tuned within `sweep_inferences_sequences.sh` and `main.sh`

## Evaluation
Results and logs will be present in `faultference/sweep_logs` and `faultference/logs`. Plots can be generated from scripts in `plots/`.
