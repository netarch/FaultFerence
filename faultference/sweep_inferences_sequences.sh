make -s clean; make -s -j8

sweep_logdir=sweep_logs/$(date +%Y-%m-%d-%H-%M)
mkdir -p ${sweep_logdir}

# Parameters
iters=10
nfails=1

for i in $(seq $iters)
do
    for topo in "topo_ft_deg14_sw245_svr686_os3_i0" "topo_ft_deg16_sw320_svr1024_os3_i0" "topo_ft_deg18_sw405_svr1458_os3_i0"
    do
        topo_dir=${sweep_logdir}/${i}/${topo}
        mkdir -p ${topo_dir}
        outfile_sim=${topo_dir}/initial
        topofile=./topologies/${topo}.edgelist

        python3 ../flow_simulator/flow_simulator.py \
            --network_file ${topofile} \
            --nfailures ${nfails} \
            --flows_file ${logdir}/flows \
            --outfile ${outfile_sim} > ${topo_dir}/flowsim_initial
        echo "Flow simulation done"
        
        for sequence_mode in "Intelligent" "Random"
        do
            for inference_mode in "Flock" "Baseline"
            do
                echo "*** Iteration" $i $sequence_mode $inference_mode $topo  >> ${topo_dir}/logs 2>&1
                ./main.sh $sequence_mode $inference_mode $topo $outfile_sim >> ${topo_dir}/logs 2>&1
            done
        done
    done
done