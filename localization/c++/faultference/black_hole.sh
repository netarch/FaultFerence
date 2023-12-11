sequence_mode=$1
inference_mode=$2

topodir=./topologies/
# topoprefix=topo_rrg_deg20_sw200_svr400_os1_i0
topoprefix=topo_ft_deg14_sw245_svr686_os3_i0
topofile=${topodir}/${topoprefix}.edgelist
logdir=logs/${topoprefix}_${sequence_mode}_${inference_mode}/$(date +%H-%M_%m-%d-%Y)

mkdir -p ${logdir}
make -s clean; make -s -j8

nfails=1
nthreads=8
maxiter=25
max_links=1

outfile_sim=${logdir}/plog_${nfails}
fail_file=${outfile_sim}.fails

python3 ../../../flow_simulator/flow_simulator.py \
    --network_file ${topofile} \
    --nfailures ${nfails} \
    --flows_file ${logdir}/flows \
    --outfile ${outfile_sim} > ${logdir}/flowsim_out
echo "Flow simulation done"

> ${logdir}/input
inputs=`echo "${fail_file} ${topofile} ${outfile_sim}"`

iter=1

eq_devices=""
eq_size=0

while [ ${iter} -le ${maxiter} ]
do
    echo ${inputs} >> ${logdir}/input
    ./black_hole_estimator_agg 0.0 1000000.01 ${nthreads} ${sequence_mode} ${inference_mode} ${inputs} > ${logdir}/temp_agg_${iter}
    cat ${logdir}/temp_agg_${iter} | grep "Best link to remove" | sed 's/(//'g | sed 's/)//'g | sed 's/,//'g | awk '{print $5" "$6}' | head -n${max_links} > ${logdir}/links_to_remove_${iter}
    new_eq_devices=`cat ${logdir}/temp_agg_${iter} | grep "equivalent devices" | grep "equivalent devices" | sed 's/equivalent devices //' | sed 's/size.*//'`
    new_eq_size=`echo ${new_eq_devices} | sed 's/]//'g | sed 's/\[//'g | awk -F',' '{print NF}'`
    if [[ "${new_eq_size}" == "${eq_size}" ]]
    then
        if [[ ${new_eq_size} -le 2 ]]
        then 
            break
        fi
    fi

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
    while read p q; do
        echo "$p $q"
        suffix=iter${iter}_r${p}_${q}
        topofile_mod=${logdir}/${topoprefix}_${suffix}.edgelist
        cat ${topofile} | grep -v "${p} ${q}" | grep -v "${q} ${p}"  > ${topofile_mod}
        python3 ../../../flow_simulator/flow_simulator.py \
            --network_file ${topofile_mod} \
            --nfailures ${nfails} \
            --flows_file ${logdir}/flows_${suffix} \
            --outfile ${outfile_sim}_${suffix} > ${logdir}/flowsim_out_${suffix} \
            --fails_from_file \
            --fail_file ${fail_file}
            # --failed_flows_only \
        inputs=`echo "${inputs} ${topofile_mod} ${outfile_sim}_${suffix}"`
    done < ${logdir}/links_to_remove_${iter}
    (( iter++ ))
done
