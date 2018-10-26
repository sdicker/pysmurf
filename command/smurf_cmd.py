#!/usr/bin/env python3
import argparse
import numpy as np
import sys
import time
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
import pysmurf

cfg_filename = 'experiment_k7_17.cfg'


"""
A function that mimics mce_cmd. This allows the user to run specific pysmurf
commands from the command line.
"""
def make_runfile(output_dir, row_len=60, num_rows=60, data_rate=60):
    """
    Make the runfile
    """
    S = pysmurf.SmurfControl(cfg_file=os.path.join(os.path.dirname(__file__), 
        '..', 'cfg_files' , cfg_filename), smurf_cmd_mode=True, setup=False)

    with open("./runfile/runfile_template.txt") as f:
        lines = f.readlines()
        line_holder = []
        for l in lines:
            # A bunch of replacements
            if "ctime=<replace>" in l:
                timestamp = S.get_timestamp()
                S.log('Adding ctime {}'.format(timestamp))
                l = l.replace("ctime=<replace>", "ctime={}".format(timestamp))
            elif "Date:<replace>" in l:
                time_string = time.strftime("%a %b %d %H:%M:%S %Y", 
                    time.localtime())
                S.log('Adding date {}'.format(time_string))
                l = l.replace('Date:<replace>', "Date: {}".format(time_string))
            elif "row_len : <replace>" in l:
                S.log("Adding row_len {}".format(row_len))
                l = l.replace('row_len : <replace>', 
                    'row_len : {}'.format(row_len))
            elif "num_rows : <replace>" in l:
                S.log("Adding num_rows {}".format(num_rows))
                l = l.replace('num_rows : <replace>', 
                    'num_rows : {}'.format(row_len))
            elif "num_rows_reported : <replace>" in l:
                S.log("Adding num_rows_reported {}".format(num_rows))
                l = l.replace('num_rows_reported : <replace>', 
                    'num_rows_reported : {}'.format(row_len))
            elif "data_rate : <replace>" in l:
                S.log("Adding data_rate {}".format(data_rate))
                l = l.replace('data_rate : <replace>', 
                    'data_rate : {}'.format(row_len))
            line_holder.append(l)

    full_path = os.path.join(output_dir, 
        'smurf_status_{}.txt'.format(S.get_timestamp()))
    S.log("Writing to {}".format(full_path))
    with open(full_path, "w") as f1:
        f1.writelines(line_holder)


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    # Offline mode
    parser.add_argument('--offline', help='For offline debugging', 
        default=False, action='store_true')

    # Stupid log command
    parser.add_argument('--log', help='Logs input phrase', default=None,
        action='store')
    
    # TES bias commands
    parser.add_argument('--tes-bias', action='store_true', default=False,
        help='Set the tes bias. Must also set --bias-group and --bias-voltage')
    parser.add_argument('--bias-group', action='store', default=-1, type=int,
        help='The bias group to set the TES bias. If -1, then sets all.', 
        choices=np.arange(8, dtype=int))
    parser.add_argument('--bias-voltage', action='store', default=0.,type=float,
        help='The bias voltage to set')

    parser.add_argument('--tes-bump', action='store_true', default=False,
        help='Bump the TESs')
    parser.add_argument('--tes-bump-wait', action='store', default=.5,
        help='The time to stay at the high current.')



    # IV commands
    parser.add_argument('--slow-iv', action='store_true', default=False,
        help='Take IV curve using the slow method.')
    parser.add_argument('--iv-band', action='store', type=int, default=-1,
        help='The band to take the IV curve in')
    parser.add_argument('--iv-wait-time', action='store', type=float,
        default=.1, help='The wait time between steps in bias for IV taking')
    parser.add_argument('--iv-bias-high', action='store', type=float,
        default=19.9, help='The high bias in volts.')
    parser.add_argument('--iv-bias-low', action='store', type=float,
        default=0., help='The low bias in volts.')
    parser.add_argument('--iv-high-current-wait', action='store', type=float,
        default=.25, help='The time in seconds to wait in the high current mode')
    parser.add_argument('--iv-bias-step', action='store', type=float, default=.1,
        help='The bias step amplitude in units of volts.')

    # Tuning
    parser.add_argument('--tune', action='store_true', default=False,
        help='Run tuning')
    parser.add_argument('--tune-band', action='store', type=int, default=-1,
        help='The band to tune.')
    parser.add_argument('--tune-make-plot', action='store_true', default=False,
        help='Whether to make plots for tuning. This is slow.')

    parser.add_argument('--last-tune', action='store_true', default=False,
        help='Use the last tuning')

    parser.add_argument('--use-tune', action='store', type=str, default=None,
        help='The full path of a tuning file to use.')

    # Start acq
    parser.add_argument('--start-acq', action='store_true', default=False,
        help='Start the data acquisition')
    parser.add_argument('--make-runfile', action='store_true', default=False,
        help='Make a runfile. Needed for data acquistion.')
    parser.add_argument('--row-len', action='store', default=60, type=int,
        help='The variable to stuff into the runfile. See the MCE wiki')
    parser.add_argument('--num-rows', action='store', default=60, type=int,
        help='The variable to stuff into the runfile. See the MCE wiki')
    parser.add_argument('--data-rate', action='store', default=60, type=int,
        help='The variable to stuff into the runfile. See the MCE wiki')

    # Stop acq
    parser.add_argument('--stop-acq', action='store_true', default=False,
        help='Stop the data acquistion')

    # Extract inputs
    args = parser.parse_args()

    offline = args.offline

    # Check for too many commands
    n_cmds = (args.log is not None) + args.tes_bias + args.slow_iv + \
        args.tune + args.start_acq + args.stop_acq + args.make_runfile + \
        args.last_tune + (args.use_tune is not None) + args.tes_bump
    if n_cmds > 1:
        sys.exit(0)

    S = pysmurf.SmurfControl(cfg_file=os.path.join(os.path.dirname(__file__), 
        '..', 'cfg_files' , cfg_filename), smurf_cmd_mode=True, setup=False, 
        offline=offline)

    if args.log is not None:
        S.log(args.log)

    if args.tes_bias:
        if args.bias_group == -1:
            for b in np.arange(8):
                S.set_tes_bias_bipolar(b, args.bias_voltage, 
                    write_log=True)
        else:
            S.set_tes_bias_bipolar(args.bias_group, args.bias_voltage, 
                write_log=True)

    if args.tes_bump:
        S.overbias_tes(args.bias_group, overbias_wait=args.tes_bump_wait)

    if args.slow_iv:
        if args.iv_band < 0:
            S.log('Must input a valid band number using --iv-band')
        else:
            S.slow_iv(args.iv_band, wait_time=args.iv_wait_time, 
                      bias_high=args.iv_bias_high, bias_low=args.iv_bias_low,
                      high_current_wait=args.iv_high_current_wait, 
                      bias_step=args.iv_bias_step)

    if args.tune:
        # Load values from the cfg file
        tune_cfg = S.config.get("tune_band")
        if args.tune_band == -1:
            init_cfg = S.config.get("init")
            bands = np.array(init_cfg.get("bands"))
        else:
            bands = np.array(args.tune_band)
        for b in bands:
            S.log('Tuning band {}'.format(b))
            S.tune_band(b, make_plot=args.tune_make_plot,
                n_samples=tune_cfg.get('n_samples'), 
                freq_max=tune_cfg.get('freq_max'),
                freq_min=tune_cfg.get('freq_min'),
                grad_cut=tune_cfg.get('grad_cut'),
                amp_cut=tune.cfg.get('tune_cut'))

    if args.make_runfile:
        S.log('Making runfile')
        make_runfile(S.output_dir, row_len=args.row_len, num_rows=args.num_rows,
            data_rate=args.data_rate)

    if args.start_acq:
        bands = S.config.get('init').get('bands')
        S.log('Starting streaming data')
        for b in bands:
            S.stream_data_on(b)
        S.set_smurf_to_gcp_stream(True, write_log=True)

        

    if args.stop_acq:
        bands = np.array(S.config.get('init').get('bands'))
        S.log('Stopping streaming data')
        for b in bands:
            S.stream_data_off(b)
        S.set_smurf_to_gcp_stream(False, write_log=True)

