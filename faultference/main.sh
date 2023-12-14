SECONDS=0
sequence_mode=$1
inference_mode=$2
topoprefix=$3
outfile_sim=$4
logdir=$5

topodir=./topologies/
topofile=${topodir}/${topoprefix}.edgelist
flowsim_logs=${logdir}/flowsim
localization_logs=${logdir}/localization
modified_topo_dir=${logdir}/modified_topos
micro_change_dir=${logdir}/micro_changes
plog_dir=${logdir}/plog_dir

mkdir -p ${logdir} ${flowsim_logs} ${modified_topo_dir} ${localization_logs} ${micro_change_dir} ${plog_dir}

# Parameters
nfails=1
nthreads=4
maxiter=25
max_links=1

echo "nfails: ${nfails}" >> ${logdir}/config
echo "nthreads: ${nthreads}" >> ${logdir}/config
echo "maxiter: ${maxiter}" >> ${logdir}/config
echo "max_links: ${max_links}" >> ${logdir}/config


# outfile_sim=${plog_dir}/initial
fail_file=${outfile_sim}.fails

# python3 ../flow_simulator/flow_simulator.py \
#     --network_file ${topofile} \
#     --nfailures ${nfails} \
#     --flows_file ${logdir}/flows \
#     --outfile ${outfile_sim} > ${flowsim_logs}/initial
# echo "Flow simulation done"

> ${logdir}/input
inputs=`echo "${fail_file} ${topofile} ${outfile_sim}"`

iter=1
num_steps=0

eq_devices=""
eq_size=0

while [ ${iter} -le ${maxiter} ]
do
    echo ${inputs} >> ${logdir}/input
    ./estimator_agg 0.0 1000000.01 ${nthreads} ${sequence_mode} ${inference_mode} ${inputs} > ${localization_logs}/iter_${iter}
    cat ${localization_logs}/iter_${iter} | grep "Best link to remove" | sed 's/(//'g | sed 's/)//'g | sed 's/,//'g | awk '{print $5" "$6}' | head -n${max_links} > ${micro_change_dir}/iter_${iter}
    new_eq_devices=`cat ${localization_logs}/iter_${iter} | grep "equivalent devices" | grep "equivalent devices" | sed 's/equivalent devices //' | sed 's/size.*//'`
    new_eq_size=`echo ${new_eq_devices} | sed 's/]//'g | sed 's/\[//'g | awk -F',' '{print NF}'`

    if [[ "${new_eq_devices}" == "${eq_devices}" ]]
    then 
        (( unchanged++ ))
    else
        unchanged=0
    fi

    if [[ ${unchanged} -gt 2 ]]
    then
        break
    fi

    eq_devices=${new_eq_devices}
    eq_size=${new_eq_size}
    echo "Iter: $iter, Size: ${new_eq_size}, Devices: ${new_eq_devices}" >> ${logdir}/equivalent_devices
    while read p q; do
        echo "$iter ($p $q)" >> ${logdir}/steps
        (( num_steps++ ))
        echo "Removing link $p $q"
        suffix=iter${iter}_r${p}_${q}
        topofile_mod=${modified_topo_dir}/${topoprefix}_${suffix}.edgelist
        cat ${topofile} | grep -v "${p} ${q}" | grep -v "${q} ${p}"  > ${topofile_mod}
        python3 ../flow_simulator/flow_simulator.py \
            --network_file ${topofile_mod} \
            --nfailures ${nfails} \
            --flows_file ${logdir}/flows_${suffix} \
            --outfile ${plog_dir}/${suffix} > ${flowsim_logs}/${suffix} \
            --fails_from_file \
            --fail_file ${fail_file}
        inputs=`echo "${inputs} ${topofile_mod} ${plog_dir}/${suffix}"`
    done < "${micro_change_dir}/iter_${iter}"
    (( iter++ ))
done
rm -rf ${plog_dir}/*
echo $num_steps > ${logdir}/num_steps
echo $SECONDS > ${logdir}/time_taken
echo "Localization complete in $iter steps. Logs in $logdir"