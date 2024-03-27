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
active_probe_dir=${logdir}/active_probe_dir
topo_name=${topoprefix:0:8}

PYTHONHASHSEED=7

mkdir -p ${logdir} ${flowsim_logs} ${modified_topo_dir} ${localization_logs} ${micro_change_dir} ${plog_dir} ${active_probe_dir}

# Parameters
nfails=1
nthreads=2
maxiter=200
max_changes=1

echo "nfails: ${nfails}" >> ${logdir}/config
echo "nthreads: ${nthreads}" >> ${logdir}/config
echo "maxiter: ${maxiter}" >> ${logdir}/config
echo "max_changes: ${max_changes}" >> ${logdir}/config


# outfile_sim=${plog_dir}/initial
fail_file=${outfile_sim}.fails

# python3 ../flow_simulator/flow_simulator.py \
#     --network_file ${topofile} \
#     --nfailures ${nfails} \
#     --flows_file ${logdir}/flows \
#     --outfile ${outfile_sim} > ${flowsim_logs}/initial
# echo "Flow simulation done"

> ${logdir}/input
inputs=`echo "${sequence_mode} ${inference_mode} ${topo_name} ${fail_file} ${topofile} ${outfile_sim}"`

iter=1
num_steps=0

eq_devices=""
eq_size=0

while [ ${iter} -le ${maxiter} ]
do
    echo ${inputs} >> ${logdir}/input
    ./estimator_agg 0.0 1000000.01 ${nthreads} ${inputs} > ${localization_logs}/iter_${iter}
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

    micro_change_happening=$(cat ${localization_logs}/iter_${iter} | grep "Best MicroChange" | cut -d " " -f 5)
    case $micro_change_happening in 
        REMOVE_LINK)
            cat ${localization_logs}/iter_${iter} | grep "Best MicroChange" | grep "REMOVE_LINK" | sed 's/[^[0-9\.]\[*/ /g' | sed 's/[ ][ ]*/ /g' | awk '{print $1" "$2}' | head -n${max_changes} > ${micro_change_dir}/iter_${iter}
            while read p q; do
                echo "$iter ($p $q)" >> ${logdir}/steps
                (( num_steps++ ))
                echo "Removing link $p $q"
                suffix=iter${iter}_r${p}_${q}
                topofile_mod=${modified_topo_dir}/${topoprefix}_${suffix}.edgelist
                cat ${topofile} | grep -v "^${p} ${q}$" | grep -v "^${q} ${p}$"  > ${topofile_mod}
                python3 ../flow_simulator/flow_simulator.py \
                    --network_file ${topofile_mod} \
                    --nfailures ${nfails} \
                    --flows_file ${logdir}/flows_${suffix} \
                    --outfile ${plog_dir}/${suffix} > ${flowsim_logs}/${suffix} \
                    --fails_from_file \
                    --fail_file ${fail_file}
                inputs=`echo "${inputs} ${topofile_mod} ${plog_dir}/${suffix}"`
            done < "${micro_change_dir}/iter_${iter}"


            ;;
        "ACTIVE_PROBE")
            cat ${localization_logs}/iter_${iter} | grep "Best MicroChange" | grep "ACTIVE_PROBE" | sed 's/[^[0-9\.]\[*/ /g' | sed 's/[ ][ ]*/ /g' | awk '{print $1" "$2" "$3" "$4" "$5" "$6" "$7}' | head -n${max_changes} > ${micro_change_dir}/iter_${iter}
            while read src dst srcport dstport nprobes hsrc hdst; do
                echo "$iter (${src} ${dst} ${srcport} ${dstport} ${nprobes} ${hsrc} ${hdst})" >> ${logdir}/steps
                suffix=iter${iter}_a${src}_${dst}_${nprobes}
                apfile=${active_probe_dir}/${suffix}
                echo "${src} ${dst} ${srcport} ${dstport} ${nprobes} ${hsrc} ${hdst}" > ${apfile}
                (( num_steps++ ))
                echo "Active probes ${src} ${dst} ${nprobes}"
                python3 ../flow_simulator/flow_simulator.py \
                    --network_file ${topofile} \
                    --nfailures ${nfails} \
                    --flows_file ${logdir}/flows_${suffix} \
                    --outfile ${plog_dir}/${suffix} > ${flowsim_logs}/${suffix} \
                    --fails_from_file \
                    --fail_file ${fail_file} \
                    --active_probes_file ${apfile}
                inputs=`echo "${inputs} ${topofile} ${plog_dir}/${suffix}"`
            done < "${micro_change_dir}/iter_${iter}"
            ;;
        *)
            echo "Oh Boy!"
            echo ${micro_change_happening}
            ;;
        esac
        (( iter++ ))
done
tar -czvf ${logdir}/plogs.tar.gz -C ${logdir} plog_dir
rm -rf ${plog_dir}
echo $num_steps > ${logdir}/num_steps
echo $SECONDS > ${logdir}/time_taken
echo "Localization complete in $iter steps. Logs in $logdir"
