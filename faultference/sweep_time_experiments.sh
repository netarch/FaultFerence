# cd ../; make -s clean; make -s -j16;
# cd faultference;make -s clean; make -s -j16

echo "PID is " $$

sweep_logdir=sweep_logs/$(date +%Y-%m-%d-%H-%M-%S)
mkdir -p ${sweep_logdir}

# Parameters
start_index=19
iters=21
nfails=1

iteration_function() {
    i=$1

    for topo in "ft_deg10_sw125_svr250_os3_bidir_false" "ft_deg12_sw180_svr432_os3_bidir_false" "ft_deg14_sw245_svr686_os3_bidir_false" "ft_deg16_sw320_svr1024_os3_bidir_false" "ft_deg18_sw405_svr1458_os3_bidir_false" "ft_deg20_sw500_svr2000_os3_bidir_false"
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

        for sequence_mode in "Intelligent"
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
    iteration_function $i
done
wait