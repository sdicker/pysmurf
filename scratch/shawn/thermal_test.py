import time
import os
import fcntl
import sys
import epics

pause_btw_stages=True
bands=range(8)

# Dumb monitoring of FPGA temperatures
# 1399  while true; do clear; awk '{print $1" "$3}' /data/smurf_data/20190719/1563578383/outputs/1563578385_hwlog.dat | tail -n 3; sleep 1; done

def tmux_cmd(slot_number,cmd,tmux_session_name='smurf'):
    os.system("""tmux send-keys -t {}:{} '{}' C-m""".format(tmux_session_name,slot_number,cmd))

def get_eta_scan_in_progress(slot_number,band,tmux_session_name='smurf'):
    etaScanInProgress=int(epics.caget('smurf_server_s{}:AMCc:FpgaTopLevel:AppTop:AppCore:SysgenCryo:Base[{}]:CryoChannels:etaScanInProgress'.format(slot_number,band)))
    return etaScanInProgress
    
def start_hardware_logging(slot_number,filename=None):
    cmd=None
    if filename is not None:
        cmd="""S.start_hardware_logging("{}")""".format(filename)
    else:
        cmd="""S.start_hardware_logging()"""
    tmux_cmd(slot_number,cmd)

def stop_hardware_logging(slot_number):
    cmd="""S.stop_hardware_logging()"""
    tmux_cmd(slot_number,cmd)    
    
def carrier_setup(slot_number):
    cmd="""S.setup()"""
    tmux_cmd(slot_number,cmd)

def write_carrier_config(slot_number,filename):
    cmd="""S.write_config(\"{}\")""".format(filename)
    tmux_cmd(slot_number,cmd)

def write_atca_monitor_state(slot_number,filename):
    cmd="""S.write_atca_monitor_state(\"{}\")""".format(filename)
    tmux_cmd(slot_number,cmd)        

def fill_band(slot_number,band):
    cmd="""sys.argv[1]={}; exec(open("/usr/local/src/pysmurf/scratch/shawn/fill_band.py").read())""".format(band)
    tmux_cmd(slot_number,cmd)    

def add_tag_to_hardware_log(hardware_logfile,tag):
    with open(hardware_logfile,'a') as logf:
        # file locking so multiple hardware loggers running in
        # multiple pysmurf sessions can write to the same
        # requested file if desired
        fcntl.flock(logf, fcntl.LOCK_EX)
        logf.write('#' + str(tag).rstrip() + '\n')
        fcntl.flock(logf, fcntl.LOCK_UN)

def eta_scan_band(slot_number,band):
    cmd="""S.run_serial_eta_scan({})""".format(band)
    tmux_cmd(slot_number,cmd)

def get_last_line_tmux(slot_number,tmux_session_name='smurf',offset=0):
    import subprocess
    from subprocess import Popen
    p1 = subprocess.Popen(['tmux','capture-pane','-pt','{}:{}'.format(tmux_session_name,slot_number)], stdout=subprocess.PIPE)
    p2 = subprocess.Popen(['tail','-n','%d'%(1-offset)], stdin=p1.stdout, stdout=subprocess.PIPE)
    result=p2.communicate()[0].decode('UTF-8')
    return result.split('\n')[0]
    
def wait_for_text_in_tmux(slot_number,text,tmux_session_name='smurf'):
    ret=1
    while ret:
        import subprocess
        from subprocess import Popen
        p1 = subprocess.Popen(['tmux','capture-pane','-pt','{}:{}'.format(tmux_session_name,slot_number)], stdout=subprocess.PIPE)
        p2 = subprocess.Popen(['grep','-q',text], stdin=p1.stdout, stdout=subprocess.PIPE)
        p2.communicate()
        ret=p2.returncode 
    
ctime=time.time()
output_dir='/data/smurf_data/rflab_thermal_testing_swh_July2019'
hardware_logfile=os.path.join(output_dir,'{}_hwlog.dat'.format(int(ctime)))
atca_yml=os.path.join(output_dir,'{}_atca.yml'.format(int(ctime)))
server_ymls=os.path.join(output_dir,'{}'.format(int(ctime))+'_s{}.yml')

print('-> Logging to {}.'.format(hardware_logfile))

slots=[2,3,4]

wait_before_setup_min=0.1
wait_after_setup_min=5
wait_btw_band_fills_min=0.5
wait_after_band_fills_min=5
wait_btw_eta_scans_min=0.5
wait_after_eta_scans_min=10

# start hardware logging
for slot in slots:
    start_hardware_logging(slot,hardware_logfile)

print('-> Waiting {} min before setup.'.format(wait_before_setup_min))
wait_before_setup_sec=wait_before_setup_min*60
time.sleep(wait_before_setup_sec)
    
# setup
add_tag_to_hardware_log(hardware_logfile,tag='setup')
for slot in slots:      
    carrier_setup(slot)

print('-> Waiting for setup(s) to complete.')    
for slot in slots:
    wait_for_text_in_tmux(slot,"Done with setup")

print('-> Waiting {} min after setup.'.format(wait_after_setup_min))
wait_after_setup_sec=wait_after_setup_min*60
time.sleep(wait_after_setup_sec)

if pause_btw_stages:
    input('Press enter to continue ...')

# fill bands, one at a time
wait_btw_band_fills_sec=wait_btw_band_fills_min*60
for band in bands:
    add_tag_to_hardware_log(hardware_logfile,tag='b{}fill'.format(band))        
    for slot in slots:
        fill_band(slot,band)
    print('-> Waiting {} min after band {} fill.'.format(wait_btw_band_fills_min,band))            
    time.sleep(wait_btw_band_fills_sec)

print('-> Waiting {} min after band fills.'.format(wait_after_band_fills_min))
wait_after_band_fills_sec=wait_after_band_fills_min*60
time.sleep(wait_after_band_fills_sec)

if pause_btw_stages:
    input('Press enter to continue ...')

# eta scan
wait_btw_eta_scans_sec=wait_btw_eta_scans_min*60
for band in bands:
    add_tag_to_hardware_log(hardware_logfile,tag='b{}eta'.format(band))        
    for slot in slots:
        print('-> Running eta scan on slot {}, band {}...'.format(slot,band))        
        eta_scan_band(slot,band)
    time.sleep(1)
    #wait for eta scans to complete
    for slot in slots:
        while get_eta_scan_in_progress(slot,band):
            time.sleep(5)
        print('-> Eta scan for slot {}, band {} completed.'.format(slot,band))                
    print('-> All band {} eta scans completed.'.format(band))
    print('-> Waiting {} min after band {} eta scans.'.format(wait_btw_eta_scans_min,band))            
    time.sleep(wait_btw_eta_scans_sec)

print('-> Waiting {} min after eta scans.'.format(wait_after_eta_scans_min))
wait_after_eta_scans_sec=wait_after_eta_scans_min*60
time.sleep(wait_after_eta_scans_sec)

if pause_btw_stages:
    input('Press enter to continue ...')

# log atca and server ymls
# only need once
print('-> Writing ATCA state to {}.'.format(atca_yml))
write_atca_monitor_state(slots[0],atca_yml)
# right now, crashing on BUILD_DSP_G
for slot in slots:
    write_carrier_config(slot,server_ymls.format(slot))
    
# stop hardware logging
for slot in slots:
    stop_hardware_logging(slot)

