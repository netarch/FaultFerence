make -s clean; make -s -j8

echo "PID is " $$

sweep_logdir=sweep_logs/$(date +%Y-%m-%d-%H-%M-%S)
mkdir -p ${sweep_logdir}

# Parameters
iters=10
nfails=1

iteration_function() {
    i=$1
    topo=$2
    
    topo_dir=${sweep_logdir}/${topo}/${i}
    mkdir -p ${topo_dir}
    outfile_sim=${topo_dir}/initial
    topofile=./topologies/${topo}.edgelist

    python3 ../flow_simulator/flow_simulator.py \
        --network_file ${topofile} \
        --nfailures ${nfails} \
        --flows_file ${topo_dir}/flows \
        --outfile ${outfile_sim} > ${topo_dir}/flowsim_initial
    echo "Flow simulation done"

    for sequence_mode in "Intelligent" "Random"
    do
        for inference_mode in "Flock" #"Naive"
        do
            logdir=${topo_dir}/${sequence_mode}/${inference_mode}
            mkdir -p ${logdir}
            echo "*** Iteration" $i $sequence_mode $inference_mode $topo  >> ${logdir}/logs 2>&1
            ./main.sh $sequence_mode $inference_mode $topo $outfile_sim $logdir >> ${logdir}/logs 2>&1
        done
    done
}

for i in $(seq $iters)
do
    for topo in "topo_ft_deg14_sw245_svr686_os3_i0" # "topo_ft_deg16_sw320_svr1024_os3_i0" "topo_ft_deg18_sw405_svr1458_os3_i0" "topo_ft_deg20_sw500_svr2000_os3_i0"
    do        
        iteration_function $i $topo &
        sleep 10
    done
done
