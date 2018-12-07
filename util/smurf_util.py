import numpy as np
from pysmurf.base import SmurfBase
from pysmurf.command.sync_group import SyncGroup as SyncGroup
import time
import os
import struct
import time
import epics
from scipy import signal

class SmurfUtilMixin(SmurfBase):

    def take_debug_data(self, band, channel=None, nsamp=2**19, filename=None, 
            IQstream=1, single_channel_readout=1):
        """
        """
        # Set proper single channel readout
        if channel is not None:
            if single_channel_readout == 1:
                self.set_single_channel_readout(band, 1)
                self.set_single_channel_readout_opt2(band, 0)
            elif single_channel_readout == 2:
                self.set_single_channel_readout(band, 0)
                self.set_single_channel_readout_opt2(band, 1)
            else:
                self.log('single_channel_readout must be 1 or 2', 
                    self.LOG_ERROR)
                raise ValueError('single_channel_readout must be 1 or 2')
        else: # exit single channel otherwise
            self.set_single_channel_readout(band, 0)
            self.set_single_channel_readout_opt2(band, 0)

        # Set IQstream
        if IQstream==1:
            self.set_iq_stream_enable(band, 1)
        else:
            self.set_iq_stream_enable(band, 0)

        # set filename
        if filename is not None:
            data_filename = os.path.join(self.output_dir, filename+'.dat')
            self.log('Writing to file : {}'.format(data_filename),
                self.LOG_USER)
        else:
            timestamp = '%10i' % time.time()
            data_filename = os.path.join(self.output_dir, timestamp+'.dat')
            self.log('Writing to file : {}'.format(data_filename),
                self.LOG_USER)

        dtype = 'debug'
        dchannel = 0 # I don't really know what this means and I'm sorry -CY
        self.setup_daq_mux(dtype, dchannel, nsamp, band=band)

        self.log('Data acquisition in progress...', self.LOG_USER)

        self.log('Setting file name...', self.LOG_USER)

        char_array = [ord(c) for c in data_filename] # convert to ascii
        write_data = np.zeros(300, dtype=int)
        for j in np.arange(len(char_array)):
            write_data[j] = char_array[j]

        self.set_streamdatawriter_datafile(write_data) # write this

        self.set_streamdatawriter_open('True') # str and not bool

        self.set_trigger_daq(1, write_log=True) # this seems to = TriggerDM

        end_addr = self.get_waveform_end_addr(0) # not sure why this is 0

        time.sleep(1) # maybe unnecessary

        done=False
        while not done:
            done=True
            for k in range(4):
                wr_addr = self.get_waveform_wr_addr(0)
                empty = self.get_waveform_empty(k)
                if not empty:
                    done=False
            time.sleep(1)

        time.sleep(1) # do we need all of these?
        self.log('Finished acquisition', self.LOG_USER)
        
        self.log('Closing file...', self.LOG_USER)
        self.set_streamdatawriter_open('False')

        self.log('Done taking data', self.LOG_USER)

        if single_channel_readout > 0:
            f, df, sync = self.decode_single_channel(data_filename)
        else:
            f, df, sync = self.decode_data(data_filename)

        return f, df, sync

    # the JesdWatchdog will check if an instance of the JesdWatchdog is already
    # running and kill itself if there is
    def start_jesd_watchdog(self):
        import pysmurf.watchdog.JesdWatchdog as JesdWatchdog
        import subprocess
        import sys
        pid = subprocess.Popen([sys.executable,JesdWatchdog.__file__])

    def process_data(self, filename, dtype=np.uint32):
        """
        reads a file taken with take_debug_data and processes it into
           data + header

        Args:
        -----
        filename (str): path to file

        Optional:
        dtype (np dtype): datatype to cast to, defaults unsigned 32 bit int

        Returns:
        -----
        header (np array)
        data (np array)
        """
        n_chan = 2 # number of stream channels
        header_size = 4 # 8 bytes in 16-bit word

        rawdata = np.fromfile(filename, dtype='<u4').astype(dtype)

        # -1 is equiv to [] in Matlab
        rawdata = np.transpose(np.reshape(rawdata, (n_chan, -1))) 

        if dtype==np.uint32:
            header = rawdata[:2, :]
            data = np.delete(rawdata, (0,1), 0).astype(dtype)
        elif dtype==np.int32:
            header = np.zeros((2,2))
            header[:,0] = rawdata[:2,0].astype(np.uint32)
            header[:,1] = rawdata[:2,1].astype(np.uint32)
            data = np.double(np.delete(rawdata, (0,1), 0))
        elif dtype==np.int16:
            header1 = np.zeros((4,2))
            header1[:,0] = rawdata[:4,0].astype(np.uint16)
            header1[:,1] = rawdata[:4,1].astype(np.uint16)
            header1 = np.double(header1)
            header = header1[::2] + header1[1::2] * (2**16) # what am I doing
        else:
            raise TypeError('Type {} not yet supported!'.format(dtype))
        if header[1,1] == 2:
            header = np.fliplr(header)
            data = np.fliplr(data)

        return header, data

    def decode_data(self, filename, swapFdF=False):
        """
        take a dataset from take_debug_data and spit out results

        Args:
        -----
        filename (str): path to file

        Optional:
        swapFdF (bool): whether the F and dF (or I/Q) streams are flipped

        Returns:
        -----
        [f, df, sync] if iqStreamEnable = 0
        [I, Q, sync] if iqStreamEnable = 1
        """

        subband_halfwidth_MHz = 4.8 # can we remove this hardcode
        if swapFdF:
            nF = 1 # weirdly, I'm not sure this information gets used
            nDF = 0
        else:
            nF = 0
            nDF = 1

        header, rawdata = self.process_data(filename)

        # decode strobes
        strobes = np.floor(rawdata / (2**30))
        data = rawdata - (2**30)*strobes
        ch0_strobe = np.remainder(strobes, 2)
        flux_ramp_strobe = np.floor((strobes - ch0_strobe) / 2)

        # decode frequencies
        ch0_idx = np.where(ch0_strobe[:,0] == 1)[0]
        f_first = ch0_idx[0]
        f_last = ch0_idx[-1]
        freqs = data[f_first:f_last, 0]
        neg = np.where(freqs >= 2**23)[0]
        f = np.double(freqs)
        if len(neg) > 0:
            f[neg] = f[neg] - 2**24

        if np.remainder(len(f),512)==0:
            # -1 is [] in Matlab
            f = np.reshape(f, (-1, 512)) * subband_halfwidth_MHz / 2**23 
        else:
            self.log('Number of points not a multiple of 512. Cannot decode',
                self.LOG_ERROR)


        # frequency errors
        ch0_idx_df = np.where(ch0_strobe[:,1] == 1)[0]
        if len(ch0_idx_df) > 0:
            d_first = ch0_idx_df[0]
            d_last = ch0_idx_df[-1]
            dfreq = data[d_first:d_last, 1]
            neg = np.where(dfreq >= 2**23)[0]
            df = np.double(dfreq)
            if len(neg) > 0:
                df[neg] = df[neg] - 2**24

            if np.remainder(len(df), 512) == 0:
                df = np.reshape(df, (-1, 512)) * subband_halfwidth_MHz / 2**23
            else:
                self.log('Number of points not a multiple of 512. Cannot decode', 
                    self.LOG_ERROR)
        else:
            df = []

        return f, df, flux_ramp_strobe

    def decode_single_channel(self, filename, swapFdF=False):
        """
        decode take_debug_data file if in singlechannel mode

        Args:
        -----
        filename (str): path to file to decode

        Optional:
        swapFdF (bool): whether to swap f and df streams

        Returns:
        [f, df, sync] if iq_stream_enable = False
        [I, Q, sync] if iq_stream_enable = True
        """

        subband_halfwidth_MHz = 4.8 # take out this hardcode

        if swapFdF:
            nF = 1
            nDF = 0
        else:
            nF = 0
            nDF = 1

        header, rawdata = self.process_data(filename)

        # decode strobes
        strobes = np.floor(rawdata / (2**30))
        data = rawdata - (2**30)*strobes
        ch0_strobe = np.remainder(strobes, 2)
        flux_ramp_strobe = np.floor((strobes - ch0_strobe) / 2)

        # decode frequencies
        freqs = data[:,nF]
        neg = np.where(freqs >= 2**23)[0]
        f = np.double(freqs)
        if len(neg) > 0:
            f[neg] = f[neg] - 2**24

        f = np.transpose(f) * subband_halfwidth_MHz / 2**23

        dfreqs = data[:,nDF]
        neg = np.where(dfreqs >= 2**23)[0]
        df = np.double(dfreqs)
        if len(neg) > 0:
            df[neg] = df[neg] - 2**24

        df = np.transpose(df) * subband_halfwidth_MHz / 2**23

        return f, df, flux_ramp_strobe

    def take_stream_data(self, band, meas_time, gcp_mode=False):
        """
        Takes streaming data for a given amount of time
        Args:
        -----
        band (int) : The band to stream data
        meas_time (float) : The amount of time to observe for in seconds

        Returns:
        --------
        data_filename (string): The fullpath to where the data is stored
        """
        self.log('Starting to take data.', self.LOG_USER)
        data_filename = self.stream_data_on(band, gcp_mode=gcp_mode)
        time.sleep(meas_time)
        self.stream_data_off(band, gcp_mode=gcp_mode)
        self.log('Done taking data.', self.LOG_USER)
        return data_filename

    def stream_data_on(self, band, gcp_mode=True):
        """
        Turns on streaming data on specified channel

        Args:
        -----
        band (int) : The band to stream data

        Returns:
        --------
        data_filename (string): The fullpath to where the data is stored
        """
        # Check if flux ramp is non-zero
        ramp_max_cnt = self.get_ramp_max_cnt()
        if ramp_max_cnt == 0:
            self.log('Flux ramp frequency is zero. Cannot take data.', 
                self.LOG_ERROR)
        else:
            if self.get_single_channel_readout(band) and \
                self.get_single_channel_readout_opt2(band):
                self.log('Streaming all channels on band {}'.format(band), 
                    self.LOG_USER)

            # Make the data file
            timestamp = self.get_timestamp()
            data_filename = os.path.join(self.output_dir, timestamp+'.dat')
            self.log('Writing to file : {}'.format(data_filename), 
                self.LOG_USER)
            if gcp_mode:
                #self.set_streaming_datafile('/dev/null')
                self.set_gcp_datafile(data_filename)
            else:
                self.set_streaming_datafile(data_filename)
            
            # start streaming before opening file to avoid transient filter step
            self.set_stream_enable(band, 1, write_log=True)
            time.sleep(1.)

            if gcp_mode:
                self.set_smurf_to_gcp_writer(True, write_log=True)
            else:
                self.set_streaming_file_open(1)  # Open the file

            return data_filename

    def set_gcp_datafile(self, data_filename, num_averages=0, receiver_ip='192.168.3.1',
                         port_number='#3334', data_frames=1000000):
        """
        """
        config_dir = self.config.get('smurf2mce_cfg_dir')
        if config_dir is None:
            self.log('No smurf2mce directory in config file.', self.LOG_ERROR)
        
        file = open(config_dir, 'w')

        file.write('num_averages {}\n'.format(num_averages))
        file.write('receiver_ip {}\n'.format(receiver_ip))
        file.write('port_number {}\n'.format(port_number))
        file.write('data_file_name {}\n'.format(data_filename))
        file.write('data_frames {}'.format(data_frames))

        file.close()
        

    def stream_data_off(self, band, gcp_mode=True):
        """
        Turns off streaming data on specified band

        Args:
        -----
        band (int) : The band to turn off stream data
        """
        self.set_stream_enable(band, 0, write_log=True)
        if gcp_mode:
            self.set_smurf_to_gcp_writer(False, write_log=True)
            self.set_gcp_datafile('/data/cryo/mas_data_pipe')
        else:
            self.set_streaming_file_open(0)  # Close the file


    def read_stream_data(self, datafile, unwrap=True, gcp_mode=True):
        """
        Loads data taken with the fucntion stream_data_on

        Args:
        -----
        datafile (str): The full path to the data to read

        Opt Args:
        ---------
        unwrap (bool): Whether to unwrap the data
        """
        if gcp_mode:
            self.log('Treating data as GCP file')
            timestamp, phase = self.read_stream_data_gcp_save(datafile)
            return timestamp, phase


        file_writer_header_size = 2  # 32-bit words

        with open(datafile, mode='rb') as file:
            file_content = file.read()

        version = file_content[8]
        self.log('Version: %s' % (version))

        self.log('Data version {}'.format(version), self.LOG_INFO)

        if version == 0:
            smurf_header_size = 4  # 32-bit words
            header_size = file_writer_header_size + smurf_header_size
            smurf_data_size = 1024;  # 32-bit words
            nominal_frame_size = header_size + smurf_data_size;


            # Convert binary file to int array. The < indicates little-endian
            raw_dat = np.asarray(struct.unpack("<" + "i" * 
                ((len(file_content)) // 4), file_content))

            # To do : add bad frame check
            frame_start = np.ravel(np.where(1 + raw_dat/4==nominal_frame_size))
            n_frame = len(frame_start)

            I = np.zeros((512, n_frame))
            Q = np.zeros((512, n_frame))
            timestamp = np.zeros(n_frame)

            for i in np.arange(n_frame):
                timestamp[i] = raw_dat[frame_start[i]+2]
                start = frame_start[i] + header_size
                end = start + 512*2
                I[:,i] = raw_dat[start:end:2]
                Q[:,i] = raw_dat[start+1:end+1:2]

            phase = np.arctan2(Q, I)

        elif version == 1:
            # this works if we've already remove dropped frames.  
            # Use timestamp/frame counter to look for drops
            keys = ['h0', 'h1', 'version', 'crate_id', 'slot_number', 
                'number_of_channels', 'rtm_dac_config0', 'rtm_dac_config1',  
                'rtm_dac_config2', 'rtm_dac_config3', 'rtm_dac_config4', 
                'rtm_dac_config5', 'flux_ramp_increment', 'flux_ramp_start', 
                'base_rate_since_1_Hz', 'base_rate_since_TM', 'timestamp_ns', 
                'timestamp_s', 'fixed_rate_marker', 'sequence_counter', 
                'tes_relay','mce_word'
            ]

            data_keys = [f'data{i}' for i in range(4096)]

            keys.extend(data_keys)

            keys_dict = dict( zip( keys, range(len(keys)) ) )

            frames = [i for i in 
                struct.Struct('2I2BHI6Q6IH2xI2Q24x4096h').iter_unpack(file_content)]
            #frame_counter = [i[keys['sequence_counter']] for i in frames]
            #timestamp_s   = [i[keys['timestamp_s']] for i in frames]
            #timestamp_ns  = [i[keys['timestamp_ns']] for i in frames]

            phase = np.zeros((512, len(frames)))
            for i in range(512):
                k = i + 1024
                phase[i,:] = np.asarray([j[keys_dict[f'data{k}']] for j in 
                    frames])

            phase = phase.astype(float) / 2**15 * np.pi # scale to rad
            timestamp = [i[keys_dict['sequence_counter']] for i in frames]

        else:
            raise Exception(f'Frame version {version} not supported')

        if unwrap:
            phase = np.unwrap(phase, axis=-1)

        return timestamp, phase

    def read_stream_data_gcp_save(self, datafile,
        unwrap=True, downsample=1):
        """
        Reads the special data that is designed to be a copy of the GCP data.
        """
        import glob
        try:
            datafile = glob.glob(datafile+'*')[-1]
        except:
            print('datafile=%s'%datafile)

        with open(datafile, mode='rb') as file:
            file_content = file.read()

        keys = ['protocol_version','crate_id','slot_number','number_of_channels',
                'rtm_dac_config0', 'rtm_dac_config1', 'rtm_dac_config2', 'rtm_dac_config3',
                'rtm_dac_config4', 'rtm_dac_config5','flux_ramp_increment','flux_ramp_start',
                'rate_since_1Hz', 'rate_since_TM', 'nanoseconds', 'seconds', 'fixed_rate_marker',
                'sequence_counter', 'tes_relay_config', 'mce_word', 'user_word0', 'user_word1',
                'user_word2'
        ]

        data_keys = [f'data{i}' for i in range(528)]

        keys.extend(data_keys)
        keys_dict = dict( zip( keys, range(len(keys)) ) )

        frames = [i for i in struct.Struct('3BxI6Q8I5Q528i').iter_unpack(file_content)]

        phase = np.zeros((528, len(frames)))
        for i in range(528):
                phase[i,:] = np.asarray([j[keys_dict[f'data{i}']] for j in
                             frames])

        phase = phase.astype(float) / 2**15 * np.pi # where is decimal?  Is it in rad?
        timestamp = [i[keys_dict['sequence_counter']] for i in frames]

        return timestamp, phase


    def read_stream_data_daq(self, data_length, bay=0, hw_trigger=False):
        """
        """
        # Ask mitch why this is what it is...
        if bay == 0:
            stream0 = self.epics_root + ":AMCc:Stream0"
            stream1 = self.epics_root + ":AMCc:Stream1"
        else:
            stream0 = self.epics_root + ":AMCc:Stream4"
            stream1 = self.epics_root + ":AMCc:Stream5"
        
        pvs = [stream0, stream1]
        sg  = SyncGroup(pvs, skip_first=True)

        # trigger PV
        if not hw_trigger:
            self.set_trigger_daq(1, write_log=True)
        else:
            self.set_arm_hw_trigger(1, write_log=True)
            # self._caput(self.epics_root + 
            #     ':AMCc:FpgaTopLevel:AppTop:DaqMuxV2[0]:ArmHwTrigger', 1, 
            #     write_log=True)
        time.sleep(.1)
        sg.wait()

        vals = sg.get_values()

        r0 = vals[pvs[0]]
        r1 = vals[pvs[1]]
        
        return r0, r1

    def read_adc_data(self, adc_number, data_length, hw_trigger=False):
        """
        Args:
        -----
        adc_number (int):
        data_length (int):

        Opt Args:
        ---------
        hw_trigger (bool)
        """
        if adc_number > 3:
            bay = 1
            adc_number = adc_number - 4
        else:
            bay = 0

        self.setup_daq_mux('adc', adc_number, data_length)

        res = self.read_stream_data_daq(data_length, bay=bay,
            hw_trigger=hw_trigger)
        dat = res[1] + 1.j * res[0]

        return dat

    def read_dac_data(self, dac_number, data_length, hw_trigger=False):
        """
        Read the data directly off the DAC
        """
        if dac_number > 3:
            bay = 1
            dac_number = dac_number - 4
        else:
            bay = 0

        self.setup_daq_mux('dac', dac_number, data_length)

        res = self.read_stream_data_daq(data_length, bay=bay, 
            hw_trigger=hw_trigger)
        dat = res[1] + 1.j * res[0]

        return dat

    def setup_daq_mux(self, converter, converter_number, data_length, band=0):
        """
        Sets up for either ADC or DAC data taking.

        Args:
        -----
        converter (str) : Whether it is the ADC or DAC. choices are 'adc', 
            'dac', or 'debug'. The last one takes data on a single band.
        converter_number (int) : The ADC or DAC number to take data on.
        data_length (int) : The amount of data to take.
        band (int): which band to get data on
        """
        if converter.lower() == 'adc':
            daq_mux_channel0 = (converter_number + 1)*2
            daq_mux_channel1 = daq_mux_channel0 + 1
        elif converter.lower() == 'dac':
            daq_mux_channel0 = (converter_number + 1)*2 + 10
            daq_mux_channel1 = daq_mux_channel0 + 1
        else:
            if band==2:
                daq_mux_channel0 = 22 # these come from the mysterious mind of Steve
                daq_mux_channel1 = 23
            elif band==3:
                daq_mux_channel0 = 24
                daq_mux_channel1 = 25
            else:
                self.log("Error! Cannot take debug data on this band", 
                    self.LOG_ERROR)


        # setup buffer size
        self.set_buffer_size(data_length)

        # input mux select
        self.set_input_mux_sel(0, daq_mux_channel0, write_log=True)
        self.set_input_mux_sel(1, daq_mux_channel1, write_log=True)


    def set_buffer_size(self, size):
        """
        Sets the buffer size for reading and writing DAQs

        Args:
        -----
        size (int) : The buffer size in number of points
        """
        # Change DAQ data buffer size

        # Change waveform engine buffer size
        self.set_data_buffer_size(size, write_log=True)
        for daq_num in np.arange(4):
            s = self.get_waveform_start_addr(daq_num, convert=True, 
                write_log=False)
            e = s + 4*size
            self.set_waveform_end_addr(daq_num, e, convert=True, 
                write_log=False)
            self.log('DAQ number {}: start {} - end {}'.format(daq_num, s, e))

    def config_cryo_channel(self, band, channel, frequencyMHz, amplitude, 
        feedback_enable, eta_phase, eta_mag):
        """
        Set parameters on a single cryo channel

        Args:
        -----
        band (int) : The band for the channel
        channel (int) : which channel to configure
        frequencyMHz (float) : the frequency offset from the subband center in MHz
        amplitude (int) : amplitude scale to set for the channel (0..15)
        feedback_enable (bool) : whether to enable feedback for the channel
        eta_phase (float) : feedback eta phase, in degrees (-180..180) 
        eta_mag (float) : feedback eta magnitude
        """

        n_subbands = self.get_number_sub_bands(band)
        digitizerFrequencyMHz = self.get_digitizer_frequency_mhz(band)
        subband_width = digitizerFrequencyMHz / (n_subbands / 2)

        # some checks to make sure we put in values within the correct ranges

        if frequencyMHz > subband_width / 2:
            self.log("frequencyMHz exceeds subband width! setting to top of subband")
            freq = subband_width / 2
        elif frequencyMHz < - subband_width / 2:
            self.log("frequencyMHz below subband width! setting to bottom of subband")
            freq = -subband_width / 2
        else:
            freq = frequencyMHz

        if amplitude > 15:
            self.log("amplitude too high! setting to 15")
            ampl = 15
        elif amplitude < 0:
            self.log("amplitude too low! setting to 0")
            ampl = 0
        else:
            ampl = amplitude

        # get phase within -180..180
        phase = eta_phase
        while phase > 180:
            phase = phase - 360
        while phase < -180:
            phase = phase + 360

        # now set all the PV's
        self.set_center_frequency_mhz_channel(band, channel, freq)
        self.set_amplitude_scale_channel(band, channel, ampl)
        self.set_eta_phase_degree_channel(band, channel, phase)
        self.set_eta_mag_scaled_channel(band, channel, eta_mag)

        return

    def which_on(self, band):
        '''
        Finds all detectors that are on.

        Args:
        -----
        band (int) : The band to search.

        Returns:
        --------
        channels_on (int array) : The channels that are on
        '''
        amps = self.get_amplitude_scale_array(band)
        return np.ravel(np.where(amps != 0))

    def band_off(self, band, **kwargs):
        '''
        Turns off all tones in a band
        '''
        self.set_amplitude_scales(band, 0, **kwargs)
        self.set_feedback_enable_array(band, np.zeros(512, dtype=int), **kwargs)
        self.set_cfg_reg_ena_bit(0, wait_after=.11, **kwargs)

    def channel_off(self, band, channel, **kwargs):
        """
        Turns off tones for a single channel
        """
        self.log('Turning off band {} channel {}'.format(band, channel), 
            self.LOG_USER)
        self.set_amplitude_scale_channel(band, channel, 0, **kwargs)
        self.set_feedback_enable_channel(band, channel, 0, **kwargs)

    def set_feedback_limit_khz(self, band, feedback_limit_khz):
        '''
        '''
        digitizer_freq_mhz = self.get_digitizer_frequency_mhz(band)
        bandcenter = self.get_band_center_mhz(band)
        n_subband = self.get_number_sub_bands(band)

        subband_bandwidth = 2 * digitizer_freq_mhz / n_subband
        desired_feedback_limit_mhz = feedback_limit_khz/1000.

        if desired_feedback_limit_mhz > subband_bandwidth/2:
            desired_feedback_limit_mhz = subband_bandwidth/2

        desired_feedback_limit_dec = np.floor(desired_feedback_limit_mhz/
            (subband_bandwidth/2.))

    # if no guidance given, tries to reset both
    def recover_jesd(self,recover_jesd_rx=True,recover_jesd_tx=True):
        if recover_jesd_rx:
            #1. Toggle JesdRx:Enable 0x3F3 -> 0x0 -> 0x3F3
            self.set_jesd_rx_enable(0x0)
            self.set_jesd_rx_enable(0x3F3)

        if recover_jesd_tx:
            #1. Toggle JesdTx:Enable 0x3CF -> 0x0 -> 0x3CF
            self.set_jesd_tx_enable(0x0)
            self.set_jesd_tx_enable(0x3CF)

            #2. Toggle AMCcc:FpgaTopLevel:AppTop:AppCore:MicrowaveMuxCore[0]:DAC[0]:JesdRstN 0x1 -> 0x0 -> 0x1
            self.set_jesd_reset_n(0,0x0)
            self.set_jesd_reset_n(0,0x1)

            #3. Toggle AMCcc:FpgaTopLevel:AppTop:AppCore:MicrowaveMuxCore[0]:DAC[1]:JesdRstN 0x1 -> 0x0 -> 0x1
            self.set_jesd_reset_n(1,0x0)
            self.set_jesd_reset_n(1,0x1)

        # probably overkill...shouldn't call this function if you're not going to do anything 
        if (recover_jesd_rx or recover_jesd_tx):
            # powers up the SYSREF which is required to sync fpga and adc/dac jesd
            self.run_pwr_up_sys_ref()

        # check if Jesds recovered - enable printout
        (jesd_tx_ok,jesd_rx_ok)=self.check_jesd(silent_if_valid=False)
                
        # raise exception if failed to recover
        if (jesd_rx_ok and jesd_tx_ok):
            self.log('Recovered Jesd.', self.LOG_USER)
        else:
            which_jesd_down='Jesd Rx and Tx are both down'
            if (jesd_rx_ok or jesd_tx_ok):
                which_jesd_down = ('Jesd Rx is down' if jesd_tx_ok else 'Jesd Tx is down')
            self.log('Failed to recover Jesds ...', self.LOG_ERROR)
            raise ValueError(which_jesd_down)

    def jesd_decorator(decorated):
        def jesd_decorator_function(self):
            # check JESDs
            (jesd_tx_ok0,jesd_rx_ok0)=self.check_jesd(silent_if_valid=True)
            
            # if either JESD is down, try to fix
            if not (jesd_rx_ok0 and jesd_tx_ok0):
                which_jesd_down0='Jesd Rx and Tx are both down'
                if (jesd_rx_ok0 or jesd_tx_ok0):
                    which_jesd_down0 = ('Jesd Rx is down' if jesd_tx_ok0 else 'Jesd Tx is down')
                    
                self.log('%s ... will attempt to recover.'%which_jesd_down0, self.LOG_ERROR)

                # attempt to recover ; if it fails it will assert
                self.recover_jesd(recover_jesd_rx=(not jesd_rx_ok0),recover_jesd_tx=(not jesd_tx_ok0))

                # rely on recover to assert if it failed
                self.log('Successfully recovered Jesd but may need to redo some setup ... rerun command at your own risk.', self.LOG_USER)

            # don't continue running the desired command by default. 
            # just because Jesds are back doesn't mean we're in a sane
            # state.  User may need to relock/etc.
            if (jesd_rx_ok0 and jesd_tx_ok0):
                decorated()
                
        return jesd_decorator_function

    def check_jesd(self,silent_if_valid=False):
        # JESD Tx
        jesd_tx_enable = self.get_jesd_tx_enable()
        jesd_tx_valid = self.get_jesd_tx_data_valid()
        jesd_tx_ok = (jesd_tx_enable==jesd_tx_valid)
        if not jesd_tx_ok:
            self.log("JESD Tx DOWN", self.LOG_ERROR)
        else:
            if not silent_if_valid:
                self.log("JESD Tx Okay", self.LOG_USER)

        # JESD Rx
        jesd_rx_enable = self.get_jesd_rx_enable()
        jesd_rx_valid = self.get_jesd_rx_data_valid()
        jesd_rx_ok = (jesd_rx_enable==jesd_rx_valid)        
        if not jesd_rx_ok:
            self.log("JESD Rx DOWN", self.LOG_ERROR)
        else:
            if not silent_if_valid:
                self.log("JESD Rx Okay", self.LOG_USER)
        return (jesd_tx_ok,jesd_rx_ok)

    def get_fpga_status(self):
        '''
        Loads FPGA status checks if JESD is ok.

        Returns:
        ret (dict) : A dictionary containing uptime, fpga_version, git_hash,
            build_stamp, jesd_tx_enable, and jesd_tx_valid
        '''
        uptime = self.get_fpga_uptime()
        fpga_version = self.get_fpga_version()
        git_hash = self.get_fpga_git_hash()
        build_stamp = self.get_fpga_build_stamp()

        git_hash = ''.join([chr(y) for y in git_hash]) # convert from int to ascii
        build_stamp = ''.join([chr(y) for y in build_stamp])

        self.log("Build stamp: " + str(build_stamp), self.LOG_USER)
        self.log("FPGA version: Ox" + str(fpga_version), self.LOG_USER)
        self.log("FPGA uptime: " + str(uptime), self.LOG_USER)

        jesd_tx_enable = self.get_jesd_tx_enable()
        jesd_tx_valid = self.get_jesd_tx_data_valid()
        if jesd_tx_enable != jesd_tx_valid:
            self.log("JESD Tx DOWN", self.LOG_USER)
        else:
            self.log("JESD Tx Okay", self.LOG_USER)

        jesd_rx_enable = self.get_jesd_rx_enable()
        jesd_rx_valid = self.get_jesd_rx_data_valid()
        if jesd_rx_enable != jesd_rx_valid:
            self.log("JESD Rx DOWN", self.LOG_USER)
        else:
            self.log("JESD Rx Okay", self.LOG_USER)


        # dict containing all values
        ret = {
            'uptime' : uptime,
            'fpga_version' : fpga_version,
            'git_hash' : git_hash,
            'build_stamp' : build_stamp,
            'jesd_tx_enable' : jesd_tx_enable,
            'jesd_tx_valid' : jesd_tx_valid,
            'jesd_rx_enable': jesd_rx_enable,
            'jesd_rx_valid' : jesd_rx_valid,
        }

        return ret

    def freq_to_subband(self, freq, band):
        '''Look up subband number of a channel frequency

        To do: This probably should not be hard coded. If these values end
        up actually being persistent, we should move them into base class.

        Args:
        -----
        freq (float): frequency in MHz
        band (float): The band to place the resonator

        Returns:
        --------
        subband_no (int): subband (0..128) of the frequency within the band
        offset (float): offset from subband center
        '''
        dig_freq = self.get_digitizer_frequency_mhz(band)
        num_subband = self.get_number_sub_bands(band)
        band_center = self.get_band_center_mhz(band)
        subband_width = 2*dig_freq/num_subband
        
        subbands, subband_centers = self.get_subband_centers(band, as_offset=False)

        df = np.abs(freq - subband_centers)
        idx = np.ravel(np.where(df == np.min(df)))[0]

        subband_no = subbands[idx]
        offset = freq - subband_centers[idx]

        return subband_no, offset

    def channel_to_freq(self, band, channel):
        """
        Gives the frequency of the channel.

        Args:
        -----
        band (int) : The band the channel is in
        channel (int) :  The channel number

        Ret:
        ----
        freq (float): The channel frequency in MHz
        """
        if band is None or channel is None:
            return None

        subband = self.get_subband_from_channel(band, channel)
        _, sbc = self.get_subband_centers(band, as_offset=False)
        offset = self.get_center_frequency_mhz_channel(band, channel)

        return sbc[subband] + offset


    def get_channel_order(self, channel_orderfile=None):
        ''' produces order of channels from a user-supplied input file


        To Do : un-hardcode this.

        Args:
        -----

        Optional Args:
        --------------
        channelorderfile (str): path to a file that contains one channel per line

        Returns :
        channel_order (int array) : An array of channel orders
        '''

        # to do
        # for now this is literally just a list oops
        # sorry

        if channel_orderfile is not None:
            with open(channel_orderfile) as f:
                channel_order = f.read().splitlines()
        else:
            channel_order = [384, 416, 448, 480, 144, 176, 208, 240, 400, 432,\
                464, 496, 136, 168, 200, 232, 392, 424, 456, 488,\
                152, 184, 216, 248, 408, 440, 472, 504, 132, 164, 196, 228,\
                388, 420, 452, 484, 148, 180, 212, 244, 404, 436, 468, 500,\
                140, 172, 204, 236, 396, 428, 460, 492, 156, 188, 220, 252,\
                412, 444, 476, 508, 130, 162, 194, 226, 386, 418, 450, 482,\
                146, 178, 210, 242, 402, 434, 466, 498, 138, 170, 202, 234,\
                394, 426, 458, 490, 154, 186, 218, 250, 410, 442, 474, 506,\
                134, 166, 198, 230, 390, 422, 454, 486, 150, 182, 214, 246,\
                406, 438, 470, 502, 142, 174, 206, 238, 398, 430, 462, 494,\
                158, 190, 222, 254, 414, 446, 478, 510, 129, 161, 193, 225,\
                385, 417, 449, 481, 145, 177, 209, 241, 401, 433, 465, 497,\
                137, 169, 201, 233, 393, 425, 457, 489, 153, 185, 217, 249,\
                409, 441, 473, 505, 133, 165, 197, 229, 389, 421, 453, 485,\
                149, 181, 213, 245, 405, 437, 469, 501, 141, 173, 205, 237,\
                397, 429, 461, 493, 157, 189, 221, 253, 413, 445, 477, 509,\
                131, 163, 195, 227, 387, 419, 451, 483, 147, 179, 211, 243,\
                403, 435, 467, 499, 139, 171, 203, 235, 395, 427, 459, 491,\
                155, 187, 219, 251, 411, 443, 475, 507, 135, 167, 199, 231,\
                391, 423, 455, 487, 151, 183, 215, 247, 407, 439, 471, 503,\
                143, 175, 207, 239, 399, 431, 463, 495, 159, 191, 223, 255,\
                415, 447, 479, 511, 0, 32, 64, 96, 256, 288, 320, 352,\
                16, 48, 80, 112, 272, 304, 336, 368, 8, 40, 72, 104,\
                264, 296, 328, 360, 24, 56, 88, 120, 280, 312, 344, 376,\
                4, 36, 68, 100, 260, 292, 324, 356, 20, 52, 84, 116,\
                276, 308, 340, 372, 12, 44, 76, 108, 268, 300, 332, 364,\
                28, 60, 92, 124, 284, 316, 348, 380, 2, 34, 66, 98,\
                258, 290, 322, 354, 18, 50, 82, 114, 274, 306, 338, 370,\
                10, 42, 74, 106, 266, 298, 330, 362, 26, 58, 90, 122,\
                282, 314, 346, 378, 6, 38, 70, 102, 262, 294, 326, 358,\
                22, 54, 86, 118, 278, 310, 342, 374, 14, 46, 78, 110,\
                270, 302, 334, 366, 30, 62, 94, 126, 286, 318, 350, 382,\
                1, 33, 65, 97, 257, 289, 321, 353, 17, 49, 81, 113,\
                273, 305, 337, 369, 9, 41, 73, 105, 265, 297, 329, 361,\
                25, 57, 89, 121, 281, 313, 345, 377, 5, 37, 69, 101,\
                261, 293, 325, 357, 21, 53, 85, 117, 277, 309, 341, 373,\
                13, 45, 77, 109, 269, 301, 333, 365, 29, 61, 93, 125,\
                285, 317, 349, 381, 3, 35, 67, 99, 259, 291, 323, 355,\
                19, 51, 83, 115, 275, 307, 339, 371, 11, 43, 75, 107,\
                267, 299, 331, 363, 27, 59, 91, 123, 283, 315, 347, 379,\
                7, 39, 71, 103, 263, 195, 327, 359, 23, 55, 87, 119,\
                279, 311, 343, 375, 15, 47, 79, 111, 271, 303, 335, 367,\
                31, 63, 95, 127, 287, 319, 351, 383, 128, 160, 192, 224]

        return channel_order

    def get_subband_from_channel(self, band, channel, channelorderfile=None):
        """ returns subband number given a channel number
        Args:
        root (str): epics root (eg mitch_epics)
        band (int): which band we're working in
        channel (int): ranges 0..511, cryo channel number

        Optional Args:
        channelorderfile(str): path to file containing order of channels

        Returns:
        subband (int) : The subband the channel lives in
        """

        n_subbands = self.get_number_sub_bands(band)
        n_channels = self.get_number_channels(band)

        n_chanpersubband = n_channels / n_subbands

        if channel > n_channels:
            raise ValueError('channel number exceeds number of channels')

        if channel < 0:
            raise ValueError('channel number is less than zero!')

        chanOrder = self.get_channel_order(channelorderfile)
        idx = chanOrder.index(channel)

        subband = idx // n_chanpersubband
        return int(subband)

    def get_subband_centers(self, band, as_offset=True, hardcode=False):
        """ returns frequency in MHz of subband centers
        Args:
        -----
        band (int): which band
        as_offset (bool): whether to return as offset from band center 
            (default is no, which returns absolute values)
        """

        if hardcode:
            if band == 3:
                bandCenterMHz = 5.25
            elif band == 2:
                bandCenterMHz = 5.75
            digitizerFrequencyMHz = 614.4
            n_subbands = 128
        else:
            digitizerFrequencyMHz = self.get_digitizer_frequency_mhz(band)
            bandCenterMHz = self.get_band_center_mhz(band)
            n_subbands = self.get_number_sub_bands(band)

        subband_width_MHz = 2 * digitizerFrequencyMHz / n_subbands

        subbands = list(range(n_subbands))
        subband_centers = (np.arange(1, n_subbands + 1) - n_subbands/2) * \
            subband_width_MHz/2

        if not as_offset:
            subband_centers += self.get_band_center_mhz(band)

        return subbands, subband_centers

    def get_channels_in_subband(self, band, subband, channelorderfile=None):
        """
        Returns channels in subband
        Args:
        -----
        band (int): which band
        subband (int): subband number, ranges from 0..127

        Opt Args:
        ---------
        channelorderfile (str): path to file specifying channel order
         
        Returns:
        --------
        subband_chans (int array): The channels in the subband
        """

        n_subbands = self.get_number_sub_bands(band)
        n_channels = self.get_number_channels(band)
        n_chanpersubband = int(n_channels / n_subbands)

        if subband > n_subbands:
            raise ValueError("subband requested exceeds number of subbands")

        if subband < 0:
            raise ValueError("requested subband less than zero")

        chanOrder = self.get_channel_order(channelorderfile)
        subband_chans = chanOrder[subband * n_chanpersubband : subband * \
            n_chanpersubband + n_chanpersubband]

        return subband_chans

    def iq_to_phase(self, i, q):
        """
        Changes IQ to phase

        Args:
        -----
        i (float array)
        q (float arry)

        Returns:
        --------
        phase (float array) : 
        """
        return np.unwrap(np.arctan2(q, i))


    def hex_string_to_int(self, s):
        """
        Converts hex string, which is an array of characters, into an int.

        Args:
        -----
        s (character array) : An array of chars to be turned into a single int.

        Returns:
        --------
        i (int64) : The 64 bit int
        """
        return np.int(''.join([chr(x) for x in s]),0)


    def int_to_hex_string(self, i):
        """
        Converts an int into a string of characters.

        Args:
        -----
        i (int64) : A 64 bit int to convert into hex.

        Returns:
        --------
        s (char array) : A character array representing the int
        """
        # Must be array length 300
        s = np.zeros(300, dtype=int)
        i_hex = hex(i)
        for j in np.arange(len(i_hex)):
            s[j] = ord(i_hex[j])

        return s


    def set_tes_bias_bipolar(self, bias_group, volt, do_enable=True, **kwargs):
        """
        bias_group (int): The bias group
        volt (float): The TES bias to command in voltage.

        Opt args:
        --------
        do_enable (bool) : Sets the enable bit. Default is True.
        """

        # bias_order = np.array([9, 11, 13, 15, 16, 14, 12, 10, 7, 5, 3, 1, 8, 6, 
        #     4, 2]) - 1  # -1 because bias_groups are 0 indexed. Chips are 1
        # dac_positives = np.array([2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 
        #     26, 28, 30, 32])
        # dac_negatives = np.array([1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 
        #     25, 27, 29, 31])

        bias_order = self.bias_group_to_pair[:,0]
        dac_positives = self.bias_group_to_pair[:,1]
        dac_negatives = self.bias_group_to_pair[:,2]

        dac_idx = np.ravel(np.where(bias_order == bias_group))

        dac_positive = dac_positives[dac_idx][0]
        dac_negative = dac_negatives[dac_idx][0]

        volts_pos = volt / 2
        volts_neg = - volt / 2

        if do_enable:
            self.set_tes_bias_enable(dac_positive, 2, **kwargs)
            self.set_tes_bias_enable(dac_negative, 2, **kwargs)

        self.set_tes_bias_volt(dac_positive, volts_pos, **kwargs)
        self.set_tes_bias_volt(dac_negative, volts_neg, **kwargs)

    def set_tes_bias_off(self, **kwargs):
        """
        Turns off all TES biases
        """
        for dac in np.arange(1,33):
            self.set_tes_bias_volt(dac, 0, **kwargs)

    def tes_bias_dac_ramp(self, dac, volt_min=-9.9, volt_max=9.9, step_size=.01, wait_time=.05):
        """
        """
        bias = volt_min
        while True:
            self.set_tes_bias_volt(dac, bias, wait_after=wait_time)
            bias += step_size
            if bias > volt_max:
                bias = volt_min

    def get_tes_bias_bipolar(self, bias_group, return_raw=False, **kwargs):
        """
        Returns the bias voltage in units of Volts

        Args:
        -----
        bias_group (int) : The number of the bias group

        Opt Args:
        ---------
        return_raw (bool) : Default is False. If True, returns pos and neg
           terminal values.
        """
        bias_order = self.bias_group_to_pair[:,0]
        dac_positives = self.bias_group_to_pair[:,1]
        dac_negatives = self.bias_group_to_pair[:,2]

        dac_idx = np.ravel(np.where(bias_order == bias_group))

        dac_positive = dac_positives[dac_idx][0]
        dac_negative = dac_negatives[dac_idx][0]

        volts_pos = self.get_tes_bias_volt(dac_positive, **kwargs)
        volts_neg = self.get_tes_bias_volt(dac_negative, **kwargs)
        
        if return_raw:
            return volts_pos, volts_neg
        else:
            return volts_pos - volts_neg


    def set_amplifier_bias(self, bias_hemt=None, bias_50k=None, **kwargs):
        """
        Sets the HEMT and 50 K amp (if present) voltages.  If no
        arguments given, looks for default biases in cfg
        (amplifier:hemt_Vg and amplifier:LNA_Vg).  If nothing found in
        cfg file, does nothing to either bias.  Enable is written to
        both amplifier bias DACs regardless of whether or not they are
        set to new values - need to check that this is ok.  If user
        specifies values those override cfg file defaults.  Prints
        resulting amplifier biases at the end with a short wait in
        case there's latency between setting and reading.

        Opt Args:
        ---------
        bias_hemt (float): The HEMT bias voltage in units of volts
        bias_50k (float): The 50K bias voltage in units of volts
        """

        ############################################################################
        ### 4K HEMT
        self.set_hemt_enable(**kwargs)
        # if nothing specified take default from cfg file, if 
        # it's specified there
        bias_hemt_from_cfg=False
        if bias_hemt is None and hasattr(self,'hemt_Vg'):
            bias_hemt=self.hemt_Vg
            bias_hemt_from_cfg=True
        # if user gave a value or value was found in cfg file,
        # set it and tell the user
        if not bias_hemt is None:
            if bias_hemt_from_cfg:
                self.log('Setting HEMT LNA Vg from config file to Vg={0:.{1}f}'.format(bias_hemt, 4), 
                         self.LOG_USER)
            else:
                self.log('Setting HEMT LNA Vg to requested Vg={0:.{1}f}'.format(bias_hemt, 4), 
                         self.LOG_USER)

            self.set_hemt_gate_voltage(bias_hemt, **kwargs)

        # otherwise do nothing and warn the user
        else:
            self.log('No value specified for 50K LNA Vg and didn\'t find a default in cfg (amplifier[\'hemt_Vg\']).', 
                     self.LOG_ERROR)
        ### done with 4K HEMT
        ############################################################################

        ############################################################################
        ### 50K LNA (if present - could make this smarter and more general)
        self.set_50k_amp_enable(**kwargs)
        # if nothing specified take default from cfg file, if 
        # it's specified there
        bias_50k_from_cfg=False
        if bias_50k is None and hasattr(self,'LNA_Vg'):
            bias_50k=self.LNA_Vg
            bias_50k_from_cfg=True
        # if user gave a value or value was found in cfg file,
        # set it and tell the user
        if not bias_50k is None:
            if bias_50k_from_cfg:
                self.log('Setting 50K LNA Vg from config file to Vg={0:.{1}f}'.format(bias_50k, 4), 
                         self.LOG_USER)
            else:
                self.log('Setting 50K LNA Vg to requested Vg={0:.{1}f}'.format(bias_50k, 4), 
                         self.LOG_USER)

            self.set_50k_amp_gate_voltage(bias_50k, **kwargs)

        # otherwise do nothing and warn the user
        else:
            self.log('No value specified for 50K LNA Vg and didn\'t find a default in cfg (amplifier[\'LNA_Vg\']).', 
                     self.LOG_ERROR)
        ### done with 50K LNA
        ############################################################################
        
        # add some latency in case PIC needs it 
        time.sleep(1)
        # print amplifier biases after setting Vgs
        self.print_amplifier_bias()


    def get_amplifier_biases(self, write_log=True):
        # 4K
        hemt_Id_mA=self.get_hemt_drain_current()
        hemt_gate_bias_volts=self.get_hemt_gate_voltage()

        # 50K
        fiftyk_Id_mA=self.get_50k_amp_drain_current()
        fiftyk_amp_gate_bias_volts=self.get_50k_amp_gate_voltage()
        
        ret = {
            'hemt_Vg' : hemt_gate_bias_volts,
            'hemt_Id' : hemt_Id_mA,
            '50K_Vg' : fiftyk_amp_gate_bias_volts,
            '50K_Id' : fiftyk_Id_mA
        }

        if write_log:
            self.log(ret)

        return ret

    # alias
    get_amplifier_bias = get_amplifier_biases

    def get_hemt_drain_current(self, hemt_offset=.100693):
        """
        Returns:
        --------
        cur (float): Drain current in mA
        """

        # These values are hard coded and empirically found by Shawn
        # hemt_offset=0.100693  #Volts
        hemt_Vd_series_resistor=200  #Ohm
        hemt_Id_mA=2.*1000.*(self.get_cryo_card_hemt_bias()-
            hemt_offset)/hemt_Vd_series_resistor

        return hemt_Id_mA

    def get_50k_amp_drain_current(self):
        """
        Returns:
        --------
        cur (float): The drain current in mA
        """
        asu_amp_Vd_series_resistor=10 #Ohm
        asu_amp_Id_mA=2.*1000.*(self.get_cryo_card_50k_bias()/
            asu_amp_Vd_series_resistor)

        return asu_amp_Id_mA

    def overbias_tes(self, bias_group, overbias_voltage=19.9, overbias_wait=5.,
        tes_bias=19.9, cool_wait=20., high_current_mode=False):
        """
        Warning: This is horribly hardcoded. Needs a fix soon.

        Args:
        -----
        bias_group (int): The bias group to overbias

        Opt Args:
        ---------
        overbias_voltage (float): The value of the TES bias in the high current
            mode. Default 19.9.
        overbias_wait (float): The time to stay in high current mode in seconds.
            Default is .5
        tes_bias (float): The value of the TES bias when put back in low current
            mode. Default is 19.9.
        cool_wait (float): The time to wait after setting the TES bias for 
            transients to die off.
        """
        # drive high current through the TES to attempt to drive normal
        self.set_tes_bias_bipolar(bias_group, overbias_voltage)
        time.sleep(.1)

        self.set_tes_bias_high_current(bias_group)
        self.log('Driving high current through TES. ' + \
            'Waiting {}'.format(overbias_wait), self.LOG_USER)
        time.sleep(overbias_wait)
        if not high_current_mode:
            self.set_tes_bias_low_current(bias_group)
            time.sleep(.1)
        self.set_tes_bias_bipolar(bias_group, tes_bias)
        self.log('Waiting %.2f seconds to cool' % (cool_wait), self.LOG_USER)
        time.sleep(cool_wait)
        self.log('Done waiting.', self.LOG_USER)

    def overbias_tes_all(self, overbias_voltage=19.9, overbias_wait=0.5,
        tes_bias=19.9, cool_wait=20., high_current_mode=False):
        """
        Warning: This is horribly hardcoded. Needs a fix soon.
        CY edit 20181119 to make it even worse lol

        Args:
        -----

        Opt Args:
        ---------
        overbias_voltage (float): The value of the TES bias in the high current
            mode. Default 19.9.
        overbias_wait (float): The time to stay in high current mode in seconds.
            Default is .5
        tes_bias (float): The value of the TES bias when put back in low current
            mode. Default is 19.9.
        cool_wait (float): The time to wait after setting the TES bias for 
            transients to die off.
        """
        # drive high current through the TES to attempt to drive normal

        bias_groups = np.arange(8)

        for g in bias_groups:
            self.set_tes_bias_bipolar(g, overbias_voltage)
            time.sleep(.1)

        for g in bias_groups:
            self.set_tes_bias_high_current(g)
        self.log('Driving high current through TES. ' + \
            'Waiting {}'.format(overbias_wait), self.LOG_USER)
        time.sleep(overbias_wait)

        if not high_current_mode:
            for g in bias_groups:
                self.set_tes_bias_low_current(g)
                time.sleep(.1)

        for g in bias_groups:
            self.set_tes_bias_bipolar(g, tes_bias)
        self.log('Waiting %.2f seconds to cool' % (cool_wait), self.LOG_USER)
        time.sleep(cool_wait)
        self.log('Done waiting.', self.LOG_USER)




    def set_tes_bias_high_current(self, bias_group):
        """
        Sets the bias group to high current mode. Note that the bias group
        number is not the same as the relay number. The conversion is
        handled in this function.

        Args:
        -----
        bias_group (int): The bias group to set to high current mode
        """
        old_relay = self.get_cryo_card_relays()
        old_relay = self.get_cryo_card_relays()
        self.log('Old relay {}'.format(bin(old_relay)))
        if bias_group < 16:
            r = np.ravel(self.pic_to_bias_group[np.where(
                self.pic_to_bias_group[:,1]==bias_group)])[0]
        else:
            r = bias_group
        new_relay = (1 << r) | old_relay
        self.log('New relay {}'.format(bin(new_relay)))
        self.set_cryo_card_relays(new_relay, write_log=True)
        self.get_cryo_card_relays()

    def set_tes_bias_low_current(self, bias_group):
        """
        Sets the bias group to low current mode. Note that the bias group
        number is not the same as the relay number. The conversion is
        handled in this function.

        Args:
        -----
        bias_group (int): The bias group to set to low current mode
        """
        old_relay = self.get_cryo_card_relays()
        old_relay = self.get_cryo_card_relays()
        self.log('Old relay {}'.format(bin(old_relay)))
        if bias_group < 16:
            r = np.ravel(self.pic_to_bias_group[np.where(
                self.pic_to_bias_group[:,1]==bias_group)])[0]
        else:
            r = bias_group
        if old_relay & 1 << r != 0:
            new_relay = old_relay & ~(1 << r)
            self.log('New relay {}'.format(bin(new_relay)))
            self.set_cryo_card_relays(new_relay, write_log=True)
            self.get_cryo_card_relays()

    def set_mode_dc(self):
        """
        Sets it DC coupling
        """
        # The 16th bit (0 indexed) is the AC/DC coupling
        self.set_tes_bias_high_current(16)

    def set_mode_ac(self):
        """
        Sets it to AC coupling
        """
        # The 16th bit (0 indexed) is the AC/DC coupling
        self.set_tes_bias_low_current(16)


    def att_to_band(self, att):
        """
        Gives the band associated with a given attenuator number
        """
        return self.att_to_band['band'][np.ravel(
            np.where(self.att_to_band['att']==att))[0]]

    def band_to_att(self, band):
        """
        """
        return self.att_to_band['att'][np.ravel(
            np.where(self.att_to_band['band']==band))[0]]


    def make_gcp_mask_file(self, bands=[2,3], channels_per_band=512):
        """
        """
        chs = np.array([])
        for b in bands:
            chs = np.append(chs, self.which_on(b)+b*channels_per_band)

        return chs

    def flux_ramp_rate_to_PV(self, val):
        """
        Convert between the desired flux ramp reset rate and the PV number
        for the timing triggers.

        Hardcoded somewhere that we can't access; this is just a lookup table
        Allowed reset rates (kHz): 1, 2, 3, 4, 5, 6, 8, 10, 12, 15

        Returns:
        rate_sel (int): the rate sel PV for the timing trigger
        """

        rates_kHz = np.array([15, 12, 10, 8, 6, 5, 4, 3, 2, 1])

        try:
            idx = np.where(rates_kHz == val)[0][0] # weird numpy thing sorry
            return idx
        except IndexError:
            self.log("Reset rate not allowed! Look up help for allowed values")
            return

    def flux_ramp_PV_to_rate(self, val):
        """
        Convert between PV number in timing triggers and output flux ramp reset rate

        Returns:
        reset_rate (int): the flux ramp reset rate, in kHz
        """

        rates_kHz = [15, 12, 10, 8, 6, 5, 4, 3, 2, 1]
        return rates_kHz[val]  

    def why(self):
        """
        Why not?
        """

        aphorisms = ['If stupidity is trying the same thing over and over and hoping for different results, then let’s all be a little stupid from time to time.', 'None of it matters anyways.', 'Being and truth are continents divided by an ocean of nothingness.', 'Self-reference is the enemy of aphorism.', 'Spring marks the symbolic return of life inevitably doomed come deathly winter.', 'In this frozen wasteland we are free to abandon all hope.', 'Life is a lone, desperate howl into an infinite abyss that can neither comprehend nor respond.', 'The only absolute knowledge attainable by man is that life is meaningless.', 'That which sustains you will eventually destroy you.', 'Oh no. We are in the hands of engineers!', 'Because I said so.', 'No idea, but hopefully Mitch fixes it.', 'Party parrot!!!', 'There are some enterprises in which a careful disorderliness is the true method.', 'Not sure, maybe try eating an orange?', 'Probably just best to go home and take a nap.']

        self.log(np.random.choice(aphorisms))
        return

    def read_smurf_to_gcp_config(self):
        """
        Toggles the smurf_to_gcp read bit.
        """
        self.log('Reading SMuRF to GCP config file')
        self.set_smurf_to_gcp_cfg_read(True, wait_after=.1)
        self.set_smurf_to_gcp_cfg_read(False)

    def make_smurf_to_gcp_config(self, num_averages=0, filename=None,
                                 file_name_extend=False, 
                                 data_frames=2000000,
                                 filter_order=4, filter_freq=63):
        """
        Makes the config file that the Joe-writer uses to set the IP
        address, port number, data file name, etc.

        The IP and port are set in the config file. They cannot be updated
        in runtime. 

        Opt args:
        ---------
        num_averages (int): If 0, SMuRF output fromes to MCE are triggered
           by the sync box. A new frame is generated for each sync word.
           If > 0, then an output frame is generated for every num_averages
           number of smurf frames.
        filename (str): The filename to save the data to. If not provided,
           automatically uses the current timestamp.
        filename_extend (bool): If True, appends the data file name with 
           the current timestamp. This is a relic of Joes original code.
           Default is False and should probably always be False.
        data_frames (int): The number of frames to store. Works up to 
           2000000, which is about a 5GB file. Default is 2000000
        filter_order (int): The order of the Butterworth filter. Default 4.
        filter_freq (float): The frequency of the lowpass. Default 63.
        """
        if filename is None:
            filename = self.get_timestamp() + '.dat'
        data_file_name = os.path.join(self.data_dir, filename)
        
        flux_ramp_freq = self.get_flux_ramp_freq() * 1E3  # in Hz
        if flux_ramp_freq < 1000:
            flux_ramp_freq = 4000
            self.log('Flux ramp frequency is below 1kHz.'\
                      ' Setting a filter using 4kHz')

        self.log('Making SMuRF to MCE config file.')

        b, a = signal.butter(filter_order, 2*filter_freq / flux_ramp_freq)

        with open(self.smurf_to_mce_file, "w") as f:
            f.write("num_averages " + str(num_averages) + '\n');
            f.write("receiver_ip " + self.smurf_to_mce_ip + '\n');
            f.write("port_number " + str(self.smurf_to_mce_port) + '\n')
            f.write("data_file_name " + data_file_name + '\n');
            f.write("file_name_extend " + str(int(file_name_extend)) + '\n')
            f.write("data_frames " + str(data_frames) + '\n')
            f.write("filter_order " + str(filter_order) +"\n");
            for n in range(0,filter_order+1):
                f.write("filter_a"+str(n)+" "+str(a[n]) + "\n")
            for n in range(0,filter_order+1):
                f.write("filter_b"+str(n)+" "+str(b[n]) + "\n")

        ret = {
            "config_file": self.smurf_to_mce_file,
            "num_averages": num_averages,
            "receiver_ip": self.smurf_to_mce_ip,
            "port_number": self.smurf_to_mce_port,
            "data_file_name": data_file_name,
            "file_name_extend": file_name_extend,
            "data_frames": data_frames,
            "flux_ramp_freq": flux_ramp_freq,
            "filter_order": filter_order,
            "filter_a": a,
            "filter_b": b
        }

        return ret
