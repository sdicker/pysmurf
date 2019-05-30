# Runlike this exec(open("band_filling_test.py").read())
# to use the pysmurf S object you've already initialized
import time
import numpy as np

bands=[0,1,2,3]
amplitude=12 
wait=True 
wait_time_sec=0.1
 
for band in bands:
    S.set_att_uc(band,0)
    S.set_dsp_enable(band,1) 
    S.set_tone_scale(band,2) 
    S.set_analysis_scale(band,3) 
    S.set_synthesis_scale(band,2) 
    channels=[] 
 
    for sb in np.arange(64,116):
    #for sb in np.arange(12,116):     
        channels.append(S.get_channels_in_subband(band,sb)[0]) 
 
    for ch in channels: 
        print(ch) 
        S.set_center_frequency_mhz_channel(band,ch,0.1*np.random.rand(1)) 
        S.set_amplitude_scale_channel(band,ch,amplitude) 
        if wait: 
            time.sleep(wait_time_sec)

print('Done with half-band filling test.')