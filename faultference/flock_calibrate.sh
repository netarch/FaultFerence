nfails=1
nthreads=8
maxiter=16

topodir=topologies
topoprefix=topo_ft_deg16_sw320_svr1024_os3_i0

logdir=calibration_logs/$(date +%Y-%m-%d-%H-%M-%S)/${topoprefix}
mkdir -p ${logdir}
touch ${logdir}/input

topofile=${topodir}/${topoprefix}.edgelist

make -s clean; make -s -j8
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
done
wait
echo "Flow simulations done"

echo ${inputs} >> ${logdir}/input

./flock_calibrate 0.0 1000000.01 ${nthreads} ${inputs} > ${logdir}/param
