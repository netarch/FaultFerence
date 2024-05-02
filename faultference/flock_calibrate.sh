nfails=1
nthreads=8
maxiter=30

make -s clean; make -s -j8
seqnum=$(date +%Y-%m-%d-%H-%M-%S)

topodir=topologies

for topoprefix in "B4" "Kdl" "UsC" "ASN2k"
do
    logdir=calibration_logs/${topoprefix}/${seqnum}
    mkdir -p ${logdir}
    touch ${logdir}/input

    topofile=${topodir}/${topoprefix}.edgelist
    inputs=""

    iter=1
    while [ ${iter} -le ${maxiter} ]
    do

        outdir=${logdir}/run${iter}
        tracefile=${outdir}/plog_${nfails}
        mkdir -p ${outdir}

        python3 ../flow_simulator/flow_simulator.py \
            --network_file ${topofile} \
            --nfailures ${nfails} \
            --flows_file ${outdir}/flows \
            --outfile ${tracefile} > ${outdir}/flowsim_out &

        inputs=`echo "${inputs} ${topofile} ${tracefile}"`
        (( iter++ ))

        if [[ $(($iter%30)) -eq 0 ]]; then
            wait
        fi
    done
    wait
    echo "Flow simulations done"

    echo ${inputs} >> ${logdir}/input

    ./flock_calibrate 0.0 1000000.01 ${nthreads} ${inputs} > ${logdir}/logs 2>&1
done
