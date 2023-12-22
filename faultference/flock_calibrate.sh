nfails=1
nthreads=8
maxiter=32

topodir=topologies
topoprefix=ft_deg20_sw500_svr2000_os3_i0

logdir=calibration_logs/${topoprefix}/$(date +%Y-%m-%d-%H-%M-%S)
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

./flock_calibrate 0.0 1000000.01 ${nthreads} ${inputs} > ${logdir}/logs 2>&1
