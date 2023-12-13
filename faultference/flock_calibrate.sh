logdir=$1

nfails=1
nthreads=8
maxiter=16

#topodir=../../ns3/topology/ft_k10_os3
#topoprefix=ns3ft_deg10_sw125_svr250_os3_i1

#topodir=../../ns3/topology/ft_k12_os3
#topoprefix=ns3ft_deg12_sw180_svr432_os3_i1

#topodir=../../ns3/topology/ft_k14_os3
#topoprefix=ns3ft_deg14_sw245_svr686_os3_i1

topodir=../../ns3/topology/ft_k16_os3
topoprefix=ns3ft_deg16_sw320_svr1024_os3_i1

topofile=${topodir}/${topoprefix}.edgelist
echo ${nfails}" "${topofile}

make -j8
mkdir -p ${logdir}
touch ${logdir}/input
inputs=""

iter=1
while [ ${iter} -le ${maxiter} ]
do

    outdir=${logdir}/run${iter}
    tracefile=${outdir}/plog_${nfails}
    mkdir -p ${outdir}

    time python3 ../flow_simulator/flow_simulator.py \
        --network_file ${topofile} \
        --nfailures ${nfails} \
        --flows_file ${outdir}/flows \
        --outfile ${tracefile} > ${outdir}/flowsim_out
    echo "flow sim done"

    inputs=`echo "${inputs} ${topofile} ${tracefile}"`
    (( iter++ ))
    sleep 3
done

echo ${inputs}
echo ${inputs} >> ${logdir}/input

time ./flock_calibrate 0.0 1000000.01 ${nthreads} ${inputs} > ${logdir}/param
