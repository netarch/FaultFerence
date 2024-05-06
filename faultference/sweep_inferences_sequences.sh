# cd ../; make -s clean; make -s -j16;
# cd faultference;make -s clean; make -s -j16

echo "PID is " $$

sweep_logdir=sweep_logs/$(date +%Y-%m-%d-%H-%M-%S)
mkdir -p ${sweep_logdir}

# Parameters
start_index=1
iters=10
nfails=1

iteration_function() {
    i=$1

    for topo in "B4" "Kdl" #"ASN2k" "UsCarrier"
    do
        topo_dir=${sweep_logdir}/${topo}/${i}
        mkdir -p ${topo_dir}
        outfile_sim=${topo_dir}/initial
        topofile=./topologies/${topo}.edgelist

        python3 ../flow_simulator/flow_simulator.py \
            --network_file ${topofile} \
            --nfailures ${nfails} \
            --flows_file ${topo_dir}/flows \
            --outfile ${outfile_sim} > ${topo_dir}/flowsim_initial
        echo "$i Flow simulation done"

        if topo -eq "campus"
            python3 microchanges-blacklist.py 1720 40
        fi

        for sequence_mode in "Intelligent" "Random"
        do
            for inference_mode in "Flock" "Naive"
            do
                for minimize_mode in "Steps" #"Cost" "Time" 
                do
                    logdir=${topo_dir}/${sequence_mode}/${inference_mode}/${minimize_mode}
                    mkdir -p ${logdir}
                    echo "*** Iteration" $i $sequence_mode $inference_mode $topo $minimize_mode  >> ${logdir}/logs 2>&1
                    ./main.sh $sequence_mode $inference_mode $minimize_mode $topo $outfile_sim $logdir >> ${logdir}/logs 2>&1
                done
            done
        done
    done
}

for i in $(seq $start_index $((start_index+iters)))
do
    iteration_function $i &
    if [[ $(($i%10)) -eq 0 ]]; then
        wait
    fi
done
wait
