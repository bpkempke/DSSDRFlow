#!/usr/bin/env python
#
# Copyright 2015 Benjamin Kempke
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import ntplib.ntplib as ntplib
from gnuradio import gr, gru, uhd, blocks
from gnuradio import eng_notation
from gnuradio import analog
from gnuradio import filter
from gnuradio import wxgui
from gnuradio.eng_option import eng_option
import gnuradio.gr.gr_threading as _threading
from optparse import OptionParser
from grc_gnuradio import blks2
from grc_gnuradio import wxgui as grc_wxgui
from gnuradio.wxgui import form, forms
from gnuradio.wxgui import scopesink2
from gnuradio.wxgui import fftsink2
import wx
import sdrp
import os
import time

# From gr-digital
from gnuradio import digital

import packet_utils
import dssdr_frontend_int as dfi
import struct
import sys
import math
import copy

import sweep_profile_reader

#import os
#print os.getpid()
#raw_input('Attach and press enter: ')

def conv_packed_binary_string_to_1_0_string(s):
    """
    '\xAF' --> '10101111'
    """
    r = []
    for ch in s:
        x = ord(ch)
        for i in range(7,-1,-1):
            t = (x >> i) & 0x1
            r.append(t)

    return ''.join(map(lambda x: chr(x + ord('0')), r))

class _queue_watcher_thread(_threading.Thread):
    def __init__(self, rcvd_pktq, callback):
        _threading.Thread.__init__(self)
        self.setDaemon(1)
        self.rcvd_pktq = rcvd_pktq
        self.callback = callback
        self.keep_running = True
        self.start()


    def run(self):
        while self.keep_running:
            msg = self.rcvd_pktq.delete_head()
            ok, payload = packet_utils.unmake_packet(msg.to_string(), int(msg.arg1()))
            if self.callback:
                self.callback(ok, payload)
	
class my_top_block(grc_wxgui.top_block_gui):
    def __init__(self, options):
	grc_wxgui.top_block_gui.__init__(self, title="DSSDR")

	self.initialized = False
	self.stopped = False

	self.options = copy.copy(options)
	self._constellation = digital.constellation_bpsk()
	self._excess_bw = options.excess_bw
	self._phase_bw = options.phase_bw
	self._freq_bw = options.freq_bw
	self._timing_bw = options.timing_bw
	self._if_freq = options.if_freq
	self._timing_max_dev= 1.5
	self._demod_class = digital.bpsk_demod  # the demodulator_class we're using
	self._chbw_factor = options.chbw_factor # channel filter bandwidth factor
	self._samples_per_second = 2e6
	self._nav_samples_per_second = 16e6
	self._down_decim = 1
	self._down_samples_per_second = self._scope_sample_rate = self._samples_per_second/self._down_decim
	self._up_samples_per_second = 1e6
	self._asm_threshold = 0
	self._access_code = None
	self._tm_packet_id = 4
	self._timestamp_id = 5
	self._down_bitrate = options.bitrate
	self._up_bitrate = options.up_bitrate
	self._up_samples_per_symbol = self._up_samples_per_second/self._up_bitrate
	self._samples_per_symbol = self._samples_per_second/self._down_decim/self._down_bitrate
	self._down_sub_freq = 25e3
	self._up_sub_freq = 25e3
	self._tm_len = 8920
	self._up_tm_len = 8920
	self._coding_method = options.coding_method
	self._up_coding_method = 'None'
	self._up_subcarrier = 'Square'
	self._rs_i = 1
	self._ccsds_channel = 38
	self._uhd_carrier_offset = 10e3
	self._turn_div = 749
	self._turn_mult = 880
	self._modulation_index = 'pi/3'
	self._up_modulation_index = 1.047
	self._max_carrier_offset = 0.1
	self._dssdr_mixer_freq = options.rf_freq
	self._up_coding_rate = '1'
	self._down_coding_rate = '1'
	self._down_conv_en = "False"
	self._down_randomizer_en = options.down_randomizer_en
	self._up_conv_en = "False"
	self._up_idle_sequence = "\\x55"
	self._down_default_gain = 64
	self._up_default_gain = 44
	self._up_en = True

        if self._access_code is None:
            self._access_code = packet_utils.default_access_code

	#Construct the lookup table for parameter-setting functions
	self.param_setters = {
		"DSSDR_CHANNEL": self.setChannel,
		"DSSDR_LO_FREQ": self.setLOFreq,
		"DSSDR_REF_FREQ": self.setRefFreq,
		"DSSDR_TURN_MULT": self.setTurnMult,
		"DSSDR_TURN_DIV": self.setTurnDiv,
		"DSSDR_UP_GAIN": self.setUpGain,
		"DSSDR_DOWN_GAIN": self.setDownGain,
		"DSSDR_UP_BITRATE": self.setUpBitrate,
		"DSSDR_DOWN_BITRATE": self.setDownBitrate,
		"DSSDR_DOWN_SAMPLE_RATE": self.setSampRate,
		"DSSDR_UP_SUB_FREQ": self.setUpSubFreq,
		"DSSDR_DOWN_SUB_FREQ": self.setDownSubFreq,
		"DSSDR_DOPPLER_REPORT": self.dopplerReport,
		"DSSDR_PN_RANGE": self.rangePN,
		"DSSDR_SEQUENTIAL_RANGE": self.rangeSequential,
		"DSSDR_DOWN_CODING_METHOD": self.setDownCodingMethod,
		"DSSDR_UP_CODING_METHOD": self.setUpCodingMethod,
		"DSSDR_DOWN_TM_LEN": self.setTMLen,
		"DSSDR_UP_TM_LEN": self.setUpTMLen,
		"DSSDR_DOWN_MOD_IDX": self.setDownModulationIndex,
		"DSSDR_UP_MOD_IDX": self.setUpModulationIndex,
		"DSSDR_DOWN_CONV_EN": self.setDownConvEn,
		"DSSDR_UP_CONV_EN": self.setUpConvEn,
		"DSSDR_ASM_TOL": self.setASMThreshold,
		"DSSDR_UP_SWEEP": self.freqSweep,
		"DSSDR_UP_IDLE": self.setUpIdleSequence,
		"DSSDR_UP_EN": self.setUpEn,
		"DSSDR_SYNC_TIME": self.syncSDRTime,
		"DSSDR_UP_SWEEP": self.freqSweep,
		"DSSDR_DOWN_ACQUIRE": self.acquireCarrier,
		"DSSDR_INPUT_SELECT": self.setPanelSelect,
		"DSSDR_REF_SELECT": self.setRefSelect,
		"DSSDR_PPS_SELECT": self.setPPSSelect
	}

	#TODO:Add status fields for things like DSSDR_REF_LOCK

	self._dssdr_channels = {
		3: [7149597994, 8400061729],
		4: [7150753857, 8401419752],
		5: [7151909723, 8402777779],
		6: [7153065586, 8404135802],
		7: [7154221449, 8405493825],
		8: [7155377316, 8406851853],
		9: [7156533179, 8408209877],
		10: [7157689045, 8409567903],
		11: [7158844908, 8410925927],
		12: [7160000771, 8412283950],
		13: [7161156637, 8413641977],
		14: [7162312500, 8415000000],
		15: [7163468363, 8416358023],
		16: [7164624229, 8417716050],
		17: [7165780092, 8419074073],
		18: [7166935955, 8420432097],
		19: [7168091821, 8421790123],
		20: [7169247684, 8423148147],
		21: [7170403551, 8424506175],
		22: [7171559414, 8425864198],
		23: [7172715277, 8427222221],
		24: [7173871143, 8428580248],
		25: [7175027006, 8429938271],
		26: [7176182869, 8431296295],
		27: [7177338735, 8432654321],
		28: [7178494598, 8434012345],
		29: [7179650464, 8435370372],
		30: [7180806327, 8436728395],
		31: [7181962190, 8438086418],
		32: [7183118057, 8439444446],
		33: [7184273920, 8440802469],
		34: [7185429783, 8442160493],
		35: [7186585649, 8443518520],
		36: [7187741512, 8444876543],
		37: [7188897378, 8446234570],
		38: [7190000000, 8450000000],
	}

	#FLOWGRAPH STUFF
	if options.test == True:
		self.u = blks2.tcp_source(
			itemsize=gr.sizeof_gr_complex*1,
			addr="",
			port=12905,
			server=True
		)
	elif options.fromfile == True:
		self.u2 = blocks.file_meta_source("iq_in.dat")
		self.u = blocks.throttle(gr.sizeof_gr_complex*1, self._samples_per_second)
	elif options.frombitlog == True:
		self.u3 = blocks.file_source(gr.sizeof_char, "bitstream_recording.in", True)
		self.u2 = blocks.uchar_to_float()
		self.u1 = blocks.throttle(gr.sizeof_float*1, self._down_bitrate)
		self.u = blocks.add_const_ff(-0.5)
	else:
		self.u = uhd.usrp_source(device_addr=options.args, stream_args=uhd.stream_args('fc32'))
		self.u.set_clock_source("external")
		self.u.set_time_source("external")
		self.u.set_samp_rate(self._samples_per_second)
		self.u.set_antenna("RX2")
		self.u.set_gain(self._down_default_gain)

		self.frontend = dfi.dssdrFrontendInterface(self.u)

	if options.debug_pps == True:
		self.debug_pps = blocks.tag_debug(gr.sizeof_gr_complex, "debug-pps", "rx_time")

	if options.tofile == True:
		self.u_tx = blocks.file_meta_sink(gr.sizeof_gr_complex, "iq_out.dat", self._up_samples_per_second)
	elif options.tonull == True:
		self.u_tx = blocks.null_sink(gr.sizeof_gr_complex)
	else:
		self.u_tx = uhd.usrp_sink(device_addr=options.args, stream_args=uhd.stream_args('fc32'))
		self.u_tx.set_clock_source("external")
		self.u_tx.set_time_source("external")
		self.u_tx.set_samp_rate(self._up_samples_per_second)
		self.u_tx.set_antenna("TX/RX")
		self.u_tx.set_gain(self._up_default_gain)

	#GUI STUFF
	if options.graphics == True:
		self.nb0 = wx.Notebook(self.GetWin(), style=wx.NB_TOP)
		self.nb0.AddPage(grc_wxgui.Panel(self.nb0), "RX")
		self.nb0.AddPage(grc_wxgui.Panel(self.nb0), "TX")
		self.nb0.AddPage(grc_wxgui.Panel(self.nb0), "Nav")
		self.Add(self.nb0)
		self.constellation_scope = scopesink2.scope_sink_c(
			self.nb0.GetPage(0).GetWin(),
			title="Scope Plot",
			sample_rate=self._scope_sample_rate,
			v_scale=0,
			v_offset=0,
			t_scale=0,
			ac_couple=False,
			xy_mode=True,
			num_inputs=1,
			trig_mode=wxgui.TRIG_MODE_AUTO,
			y_axis_label="Counts",
		)
	        self.nb0.GetPage(0).Add(self.constellation_scope.win)
		#self.constellation_scope.win.set_marker('plus')
		self._scope_is_fft = False
		self.time_scope = scopesink2.scope_sink_f(
			self.nb0.GetPage(0).GetWin(),
			title="Scope Plot",
			sample_rate=self._scope_sample_rate,
			v_scale=0,
			v_offset=0,
			t_scale=.005,
			ac_couple=False,
			xy_mode=False,
			num_inputs=1,
			trig_mode=wxgui.TRIG_MODE_AUTO,
			y_axis_label="Counts",
		)
		self.nb0.GetPage(0).Add(self.time_scope.win)
		self.nb0.GetPage(0).GetWin()._box.Hide(self.time_scope.win)
		self.fft_scope = fftsink2.fft_sink_c(
			self.nb0.GetPage(0).GetWin(),
			baseband_freq=0,
			y_per_div=10,
			y_divs=10,
			ref_level=0,
			ref_scale=2.0,
			sample_rate=self._scope_sample_rate,
			fft_size=1024,
		 	fft_rate=15,
			average=False,
			avg_alpha=None,
			title="FFT Plot",
			peak_hold=False,
		)
		self.nb0.GetPage(0).Add(self.fft_scope.win)
		self.nb0.GetPage(0).GetWin()._box.Hide(self.fft_scope.win)
	
		self.row1_sizer = wx.BoxSizer(wx.HORIZONTAL)
		self.recording_onoff_chooser = forms.radio_buttons(
			parent=self.nb0.GetPage(0).GetWin(),
			value='Off',
			callback=self.setRecording,
			label="IQ Recording",
			choices=['Off','On'],
			labels=[],
			style=wx.RA_HORIZONTAL,
		)
		self.front_panel_chooser = forms.radio_buttons(
			parent=self.nb0.GetPage(0).GetWin(),
			value='RF',
			callback=self.setPanelSelect,
			label="Input Select",
			choices=['RF','IF'],
			labels=[],
			style=wx.RA_HORIZONTAL,
		)
		self.ref_chooser = forms.radio_buttons(
			parent=self.nb0.GetPage(0).GetWin(),
			value='Internal',
			callback=self.setRefSelect,
			label="Ref Select",
			choices=['Internal','External'],
			labels=[],
			style=wx.RA_HORIZONTAL,
		)
		self.pps_chooser = forms.radio_buttons(
			parent=self.nb0.GetPage(0).GetWin(),
			value='Internal',
			callback=self.setPPSSelect,
			label="PPS Select",
			choices=['Internal','External'],
			labels=[],
			style=wx.RA_HORIZONTAL,
		)

		self.sync_button = forms.button(
			parent=self.nb0.GetPage(0).GetWin(),
			value='Sync to PPS',
			callback=self.syncSDRTime,
			choices=['Sync to PPS'],
			style=wx.RA_HORIZONTAL,
		)
		self.ref_locked_text = forms.static_text(
			parent=self.nb0.GetPage(0).GetWin(),
			value="",
			callback=self.setRefLocked,
			label="",
			converter=forms.str_converter(),
		)
		self.row1_sizer.Add(self.recording_onoff_chooser, flag=wx.ALIGN_CENTER)
		self.row1_sizer.Add(self.front_panel_chooser, flag=wx.ALIGN_CENTER)
		self.row1_sizer.Add(self.ref_chooser, flag=wx.ALIGN_CENTER)
		self.row1_sizer.Add(self.pps_chooser, flag=wx.ALIGN_CENTER)
		self.row1_sizer.Add(self.sync_button, flag=wx.ALIGN_CENTER)
		self.row1_sizer.Add(self.ref_locked_text, flag=wx.ALIGN_CENTER)
		self.nb0.GetPage(0).Add(self.row1_sizer)
		self.complex_scope_chooser = forms.radio_buttons(
			parent=self.nb0.GetPage(0).GetWin(),
			value='Constellation',
			callback=self.setComplexScopeStyle,
			label="Complex Scope",
			choices=['Constellation','FFT'],
			labels=[],
			style=wx.RA_HORIZONTAL,
		)
		self.nb0.GetPage(0).Add(self.complex_scope_chooser)
		self.scope_chooser = forms.radio_buttons(
			parent=self.nb0.GetPage(0).GetWin(),
			value='USRP',
			callback=self.setScopePoint,
			label="Scope Probe Point",
			choices=['USRP','Carrier Tracking','Sub-Carrier Costas','Sub-Carrier Sync','Data Sync'],
			labels=[],
			style=wx.RA_HORIZONTAL,
		)
		self.nb0.GetPage(0).Add(self.scope_chooser)
		self._bitrate_text_box = forms.text_box(
			parent=self.nb0.GetPage(0).GetWin(),
			value=self._down_bitrate,
			callback=self.setDownBitrate,
			label="Symbol Rate",
			converter=forms.float_converter(),
		)
		self.nb0.GetPage(0).Add(self._bitrate_text_box)
		self._samprate_text_box = forms.text_box(
			parent=self.nb0.GetPage(0).GetWin(),
			value=self._samples_per_second,
			callback=self.setSampRate,
			label="Sampling Rate",
			converter=forms.float_converter(),
		)
		self.nb0.GetPage(0).Add(self._samprate_text_box)
		self._subcfreq_text_box = forms.text_box(
			parent=self.nb0.GetPage(0).GetWin(),
			value=self._down_sub_freq,
			callback=self.setDownSubFreq,
			label="Downlink Subcarrier Frequency",
			converter=forms.float_converter(),
		)
		self.nb0.GetPage(0).Add(self._subcfreq_text_box)
		self._mod_index_chooser = forms.radio_buttons(
			parent=self.nb0.GetPage(0).GetWin(),
			value=self._modulation_index,
			callback=self.setDownModulationIndex,
			label="Modulation Index",
			choices=['pi/2', 'pi/3'],
			labels=[],
			style=wx.RA_HORIZONTAL,
		)
		self.nb0.GetPage(0).Add(self._mod_index_chooser)
		self._pktlen_text_box = forms.text_box(
			parent=self.nb0.GetPage(0).GetWin(),
			value=self._tm_len,
			callback=self.setTMLen,
			label="Downlink Packet Length (bits)",
			converter=forms.float_converter(),
		)
		self.nb0.GetPage(0).Add(self._pktlen_text_box)
		self._coding_chooser = forms.radio_buttons(
			parent=self.nb0.GetPage(0).GetWin(),
			value=self._coding_method,
			callback=self.setDownCodingMethod,
			label="Coding",
			choices=['None', 'RS', 'Turbo 1/2', 'Turbo 1/3', 'Turbo 1/4', 'Turbo 1/6'],
			labels=[],
			style=wx.RA_HORIZONTAL,
		)
		self.nb0.GetPage(0).Add(self._coding_chooser)
		self._down_conv_check_box = forms.check_box(
			parent=self.nb0.GetPage(0).GetWin(),
			value=self._down_conv_en,
			callback=self.setDownConvEn,
			label="Convolutional Decode",
			true="True",
			false="False",
		)
		self.nb0.GetPage(0).Add(self._down_conv_check_box)
		self._down_randomizer_check_box = forms.check_box(
			parent=self.nb0.GetPage(0).GetWin(),
			value=self._down_randomizer_en,
			callback=self.setDownRandomizerEn,
			label="De-randomizer",
			true=True,
			false=False,
		)
		self.nb0.GetPage(0).Add(self._down_randomizer_check_box)
		self._pktlen_text_box = forms.text_box(
			parent=self.nb0.GetPage(0).GetWin(),
			value=self._asm_threshold,
			callback=self.setASMThreshold,
			label="ASM Error Tolerance (bits)",
			converter=forms.float_converter(),
		)
		self.nb0.GetPage(0).Add(self._pktlen_text_box)
		self._coding_chooser = forms.radio_buttons(
			parent=self.nb0.GetPage(0).GetWin(),
			value=self._rs_i,
			callback=self.setRSI,
			label="Reed-Solomon Interleaving Depth",
			choices=[1,5],
			labels=[],
			style=wx.RA_HORIZONTAL,
		)
		self.nb0.GetPage(0).Add(self._coding_chooser)
		self._ccsds_chan_text_box = forms.text_box(
			parent=self.nb0.GetPage(0).GetWin(),
			value=self._ccsds_channel,
			callback=self.setChannel,
			label="CCSDS Channel",
			converter=forms.int_converter(),
		)
		self.nb0.GetPage(0).Add(self._ccsds_chan_text_box)
		self.setChannel(self._ccsds_channel)
	
		if options.test == True or options.fromfile == True or options.frombitlog == True:
			glow = 0.0
			ghigh = 1.0
			cur_g = 0.5
		else:
			g = self.u.get_gain_range()
			cur_g = self._down_default_gain
		
			# some configurations don't have gain control
			if g.stop() <= g.start():
				glow = 0.0
				ghigh = 1.0
		
			else:
				glow = g.start()
				ghigh = g.stop()
		
		self._uhd_gain_slider = wx.BoxSizer(wx.HORIZONTAL)
		form.slider_field(
			parent=self.nb0.GetPage(0).GetWin(),
			sizer=self._uhd_gain_slider,
			label="USRP RX Gain",
			weight=3,
			min=int(glow), 
			max=int(ghigh),
			value=cur_g,
			callback=self.setDownGain
		)
		self.nb0.GetPage(0).Add(self._uhd_gain_slider)

		#TX chain GUI components
		if options.test == True or options.tofile == True or options.tonull == True:
			gtxlow = 0.0
			gtxhigh = 1.0
			cur_gtx = 0.5
		else:
			gtx = self.u_tx.get_gain_range()
			cur_gtx = self._up_default_gain
		
			# some configurations don't have gain control
			if gtx.stop() <= gtx.start():
				gtxlow = 0.0
				gtxhigh = 1.0
		
			else:
				gtxlow = gtx.start()
				gtxhigh = gtx.stop()

		self._up_en_chooser = forms.check_box(
			parent=self.nb0.GetPage(1).GetWin(),
			value='True',
			callback=self.setUpEn,
			label="TX Enable",
			true='True',
			false='False',
		)
		self.nb0.GetPage(1).Add(self._up_en_chooser)

		self._uhd_tx_gain_slider = wx.BoxSizer(wx.HORIZONTAL)
		form.slider_field(
			parent=self.nb0.GetPage(1).GetWin(),
			sizer=self._uhd_tx_gain_slider,
			label="USRP TX Gain",
			weight=3,
			min=int(gtxlow), 
			max=int(gtxhigh),
			value=cur_gtx,
			callback=self.setUpGain
		)
		self.nb0.GetPage(1).Add(self._uhd_tx_gain_slider)
		self._subcfreq_up_text_box = forms.text_box(
			parent=self.nb0.GetPage(1).GetWin(),
			value=self._up_sub_freq,
			callback=self.setUpSubFreq,
			label="Uplink Subcarrier Frequency",
			converter=forms.float_converter(),
		)
		self.nb0.GetPage(1).Add(self._subcfreq_up_text_box)
		self._up_bitrate_text_box = forms.text_box(
			parent=self.nb0.GetPage(1).GetWin(),
			value=self._up_bitrate,
			callback=self.setUpBitrate,
			label="Uplink Bitrate",
			converter=forms.float_converter(),
		)
		self.nb0.GetPage(1).Add(self._up_bitrate_text_box)
		self._up_data_text_box = forms.text_box(
			parent=self.nb0.GetPage(1).GetWin(),
			value="1234ABCD",
			callback=self.txData,
			label="TX Data",
			converter=forms.str_converter(),
		)
		self.nb0.GetPage(1).Add(self._up_data_text_box)
		self._up_mod_index_chooser = forms.text_box(
			parent=self.nb0.GetPage(1).GetWin(),
			value=self._up_modulation_index,
			callback=self.setUpModulationIndex,
			label="Uplink Modulation Index",
			converter=forms.float_converter(),
		)
		self.nb0.GetPage(1).Add(self._up_mod_index_chooser)
		self._up_coding_chooser = forms.radio_buttons(
			parent=self.nb0.GetPage(1).GetWin(),
			value=self._up_coding_method,
			callback=self.setUpCodingMethod,
			label="Coding",
			choices=['None', 'RS'],
			labels=[],
			style=wx.RA_HORIZONTAL,
		)
		self.nb0.GetPage(1).Add(self._up_coding_chooser)
		self._subcarrier_chooser = forms.radio_buttons(
			parent=self.nb0.GetPage(1).GetWin(),
			value=self._up_subcarrier,
			callback=self.setUpSubcarrier,
			label="Subcarrier Type",
			choices=['Square','Sine'],
			labels=[],
			style=wx.RA_HORIZONTAL,
		)
		self.nb0.GetPage(1).Add(self._subcarrier_chooser)
		self._up_conv_check_box = forms.check_box(
			parent=self.nb0.GetPage(1).GetWin(),
			value=self._up_conv_en,
			callback=self.setUpConvEn,
			label="Convolutional Encode",
			true="True",
			false="False",
		)
		self.nb0.GetPage(1).Add(self._up_conv_check_box)
		self._up_pktlen_text_box = forms.text_box(
			parent=self.nb0.GetPage(1).GetWin(),
			value=self._up_tm_len,
			callback=self.setUpTMLen,
			label="Uplink Packet Length (bits)",
			converter=forms.float_converter(),
		)
		self.nb0.GetPage(1).Add(self._up_pktlen_text_box)
		self._uhd_offset_text_box = forms.text_box(
			parent=self.nb0.GetPage(1).GetWin(),
			value=self._uhd_carrier_offset,
			callback=self.setUHDCarrierOffset,
			label="USRP Offset Frequency (Hz)",
			converter=forms.float_converter(),
		)
		self.nb0.GetPage(1).Add(self._uhd_offset_text_box)
		self._sweep_gen_text_box = forms.text_box(
			parent=self.nb0.GetPage(1).GetWin(),
			value="rf2_1",
			callback=self.freqSweep,
			label="Frequency Sweep Profile",
			converter=forms.str_converter(),
		)
		self.nb0.GetPage(1).Add(self._sweep_gen_text_box)
		self._idle_sequence_text_box = forms.text_box(
			parent=self.nb0.GetPage(1).GetWin(),
			value=self._up_idle_sequence,
			callback=self.setUpIdleSequence,
			label="Uplink Idle Sequence",
			converter=forms.str_converter(),
		)
		self.nb0.GetPage(1).Add(self._idle_sequence_text_box)
		self._pn_ranging_text_box = forms.text_box(
			parent=self.nb0.GetPage(2).GetWin(),
			value="",
			callback=self.rangePN,
			label="Queue PN Ranging",
			converter=forms.str_converter(),
		)
		self.nb0.GetPage(2).Add(self._pn_ranging_text_box)
		self._sequential_ranging_text_box = forms.text_box(
			parent=self.nb0.GetPage(2).GetWin(),
			value="",
			callback=self.rangeSequential,
			label="Queue Sequential Ranging",
			converter=forms.str_converter(),
		)
		self.nb0.GetPage(2).Add(self._sequential_ranging_text_box)
		self.row2_sizer = wx.BoxSizer(wx.HORIZONTAL)
		self.freq_acq_button = forms.button(
			parent=self.nb0.GetPage(2).GetWin(),
			value='Acquire Carrier Offset',
			callback=self.acquireCarrier,
			choices=['Acquire Carrier Offset'],
			style=wx.RA_HORIZONTAL,
		)
		self.carrier_offset_text = forms.static_text(
			parent=self.nb0.GetPage(2).GetWin(),
			value="",
			label="",
			converter=forms.str_converter(),
		)
		self.row2_sizer.Add(self.freq_acq_button, flag=wx.ALIGN_CENTER)
		self.row2_sizer.Add(self.carrier_offset_text, flag=wx.ALIGN_CENTER)
		self.nb0.GetPage(2).Add(self.row2_sizer)


	self.file_sink = blocks.file_meta_sink(gr.sizeof_gr_complex, "iq_recording.dat", self._samples_per_second)
	self.file_sink.close()
	self.iq_recording_ctr = 0

	# Selection logic to switch between recording and normal flowgraph routes
	# NOTE: u_valve logic is implemented backwards in GNURadio....
	#self.u_valve = blks2.valve(
	#	item_size=gr.sizeof_gr_complex,
	#	open=False
	#)

	# Temporary code used to verify coherent turnaround
	self.turnaround_mixer = blocks.multiply_cc()
	self.turnaround_mixer_source = analog.sig_source_c(self._down_samples_per_second, analog.GR_SIN_WAVE, -25e3, 1.0)
	self.turnaround_iir = filter.single_pole_iir_filter_cc(0.0001)
	self.turnaround_null = blocks.null_sink(gr.sizeof_float)

	# PLL and associated carrier for tracking carrier frequency if residual carrier is used
	self.carrier_tracking = sdrp.pll_freq_acq_cc(math.pi/200, math.pi, -math.pi, int(options.acq_samples))
	self.imag_to_float = blocks.complex_to_imag()

	#Suppressed carrier requires costas after subcarrier mixer
	self.subcarrier_costas = digital.costas_loop_cc(0.001, 2)
	self.real_to_float = blocks.complex_to_real()

	#Square wave subcarrier sync
	self.subcarrier_sync = sdrp.square_sub_tracker_ff(0.001, 2*self._down_sub_freq/self._down_samples_per_second*1.0001, 2*self._down_sub_freq/self._down_samples_per_second*0.9999)

	#Data sync
	self.data_sync = sdrp.square_data_tracker_ff(0.001, self._down_bitrate/self._down_samples_per_second*1.001, self._down_bitrate/self._down_samples_per_second*0.999)

	#Data framing
	self.soft_correlator = sdrp.correlate_soft_access_tag_ff(conv_packed_binary_string_to_1_0_string('\x1A\xCF\xFC\x1D'), self._asm_threshold, "asm_corr")
	self.conv_decoder = sdrp.ccsds_tm_conv_decoder("asm_corr")
	self.de_randomizer = sdrp.ccsds_tm_derandomizer("asm_corr")
	self.tm_framer = sdrp.ccsds_tm_framer(self._tm_packet_id, self._timestamp_id, "asm_corr", "rx_time", self._down_bitrate)
	self.tm_framer.setFrameLength(self._tm_len)

	self._current_scope_block = None
	self._current_scoped_block = self.u
	self._current_scoped_block_port = 0

	self._recording = 'Off'

	#TX path in flowgraph
	self.pkt_gen_msgq = gr.msg_queue(10)
        self.pkt_gen = sdrp.ccsds_tm_tx(self._tm_packet_id, self._timestamp_id, 1.0, 16, self.pkt_gen_msgq)
	self.conj = blocks.conjugate_cc()

	#Sweep generator for transponder lock
	self.sweep_gen = sdrp.sweep_generator_cc(self._up_samples_per_second)

	# DSSDR subcarrier mixer (either 25 kHz or 0 kHz depending on baud rate)
	self.up_subcarrier_mixer = blocks.multiply_ff()
	self.subcarrier_mixer_source_tx = analog.sig_source_f(self._up_samples_per_second, analog.GR_SQR_WAVE, 25e3, 2.0, -1.0)
	self.phase_mod_tx = analog.phase_modulator_fc(self._up_modulation_index)
	self.tx_attenuator = blocks.multiply_const_cc((0.1+0.0j))

	#Add in bit recorder if needed
	if self.options.bitlog:
		self.bit_slicer = digital.binary_slicer_fb()
		self.bit_recorder = blocks.file_sink(1, "bitstream_recording.out")


	self.setDownCodingMethod(self._coding_method)
	self.setUpCodingMethod("None")
	self.setUpSubcarrier(self._up_subcarrier)
	self.setDownBitrate(self._down_bitrate)
	self.setUpBitrate(self._up_bitrate)
	self.setDownModulationIndex(self._modulation_index)
	self.setUpModulationIndex(self._up_modulation_index)
	self.setDownConvEn(self._down_conv_en)
	self.setUpConvEn(self._up_conv_en)
	self.setUpIdleSequence(self._up_idle_sequence)
	self.setDownRandomizerEn(self._down_randomizer_en)

	#Connection to outside world
	self.socket_pdu = blocks.socket_pdu("TCP_SERVER", "127.0.0.1", "12902", 10000)
	self.sdrp_interpreter = sdrp.sdrp_packet_interpreter()
	self.msg_connect(self.tm_framer, "tm_frame_out", self.sdrp_interpreter, "sdrp_pdu_in")
	self.msg_connect(self.sdrp_interpreter, "socket_pdu_out", self.socket_pdu, "pdus")
	self.msg_connect(self.socket_pdu, "pdus", self.sdrp_interpreter, "socket_pdu_in")
	self.msg_connect(self.sdrp_interpreter,"sdrp_pdu_out", self.pkt_gen, "ccsds_tx_msg_in")

	if options.test == False and options.fromfile == False and options.frombitlog == False:
		_threading.Thread(target=self.watchRef).start()

	self.initialized = True
	print "DS-SDR Initialized"

    def watchRef(self):
	while True:
		time.sleep(1)
		self.setRefLocked(self.u.get_mboard_sensor("ref_locked",0))#ref_locked()#clock_source(0)
		self.carrier_offset_text.set_value(str(self.carrier_tracking.get_frequency()/2/math.pi*self._down_samples_per_second))

    def acquireCarrier(self, arg):
	self.carrier_tracking.acquireCarrier()

    def setUpEn(self, arg):
	if arg == 'True':
		self.pkt_gen.pauseTX(False)
	else:
		self.pkt_gen.pauseTX(True)

    def setRefLocked(self, locked):
	self.ref_locked_text.set_value(locked)

    def syncSDRTime(self, arg):
	if self.options.ignore_ntp != True:
		x = ntplib.NTPClient()
		cur_time = x.request('europe.pool.ntp.org').tx_time
		self.u.set_time_unknown_pps(uhd.time_spec_t(int(cur_time)+1))
	else:
		self.u.set_time_unknown_pps(uhd.time_spec_t(int(time.time()+1)))
	#Hack to get the USRP to push an rx_time tag
	if self.options.test == False and self.options.fromfile == False and self.options.frombitlog == False:
		self.u.set_samp_rate(self._samples_per_second)

    def setUpIdleSequence(self, arg):
	self._up_idle_sequence = eval("'" + arg + "'")
	self.pkt_gen.setIdleSequence(self._up_idle_sequence)

    def setDownConvEn(self, down_conv_en):
	self._down_conv_en = (down_conv_en == 'True')
	self.conv_decoder.setConvEn(self._down_conv_en)
	self.soft_correlator.set_conv_en(self._down_conv_en)

    def setDownRandomizerEn(self, down_randomizer_en):
	self._down_randomizer_en = down_randomizer_en
	self.de_randomizer.setDerandomizerEn(self._down_randomizer_en)

    def setUpConvEn(self, up_conv_en):
	self._up_conv_en = (up_conv_en == 'True')
	self.pkt_gen.setConvEn(self._up_conv_en)

    def setPanelSelect(self, panel_choice):
	self._panel_select = panel_choice
	if self._panel_select == 'RF':
		self.frontend.selectIF(0)
	else:
		self.frontend.selectIF(1)

    def setRefSelect(self, ref_choice):
	self._ref_select = ref_choice
	if self._ref_select == 'Internal':
		self.frontend.selectRef(1)
	else:
		self.frontend.selectRef(0)

    def setPPSSelect(self, pps_choice):
	self._pps_select = pps_choice
	if self._pps_select == 'Internal':
		self.frontend.selectPPS(1)
	else:
		self.frontend.selectPPS(0)

    def setRecording(self, recording_choice):
	if self._recording == 'On':
		self.file_sink.close()
		os.rename('iq_recording.dat','iq_recording_'+str(self.iq_recording_ctr)+'.dat');
		self.iq_recording_ctr = self.iq_recording_ctr + 1
	self._recording = recording_choice
	if self._recording == 'Off':
		print "Not Recording!"
	else:
		self.file_sink.open('iq_recording.dat')
		print "Recording!"

	#Hack to make sure rx_time tag gets into file
	if self.options.test == False and self.options.fromfile == False and self.options.frombitlog == False:
		self.u.set_samp_rate(self._samples_per_second)

    def setDownModulationIndex(self, mod_idx):
	self._modulation_index = mod_idx
	if self.options.graphics == True:
		if mod_idx == 'pi/2':
			self.scope_chooser._radio_buttons.EnableItem(1, False)
			self.scope_chooser._radio_buttons.EnableItem(2, True)
		else:
			self.scope_chooser._radio_buttons.EnableItem(1, True)
			self.scope_chooser._radio_buttons.EnableItem(2, False)

	if self._modulation_index == 'pi/2': #Costas
		self.subcarrier_sync.setInput(0)
	else: #PLL
		self.subcarrier_sync.setInput(1)

    def setUpModulationIndex(self, mod_idx):
	self._up_modulation_index = mod_idx
	self.phase_mod_tx.set_sensitivity(mod_idx)

    def setupFlowgraph(self):
	self._current_scope_block = None
	if self.options.fromfile == True:
		self.connect(self.u2, self.u)
	if self.options.debug_pps == True:
		self.connect(self.u, self.debug_pps)
	if self.options.frombitlog == True:
		self.connect(self.u3, self.u2, self.u1, self.u, self.soft_correlator)
	else:
		self.connect(self.u, self.subcarrier_costas, self.real_to_float)
		self.connect(self.u, self.carrier_tracking, self.imag_to_float)
		self.connect(self.real_to_float, (self.subcarrier_sync, 0) )
		self.connect(self.imag_to_float, (self.subcarrier_sync, 1) )
		self.connect(self.subcarrier_sync, self.data_sync, self.soft_correlator)
		self.connect(self.u, self.file_sink)

	#This section of flowgraph remains the same regardless of whether we're running from bitlog or USRP
	self.connect(self.soft_correlator, self.conv_decoder, self.de_randomizer, self.tm_framer)

	if self.options.bitlog:
		self.connect(self.data_sync, self.bit_slicer, self.bit_recorder)

	#TX chain
	self.connect(self.pkt_gen, (self.up_subcarrier_mixer,0))
	self.connect(self.subcarrier_mixer_source_tx, (self.up_subcarrier_mixer,1))
	self.connect(self.up_subcarrier_mixer, self.phase_mod_tx, self.tx_attenuator, self.sweep_gen, self.conj, self.u_tx)

    def resetScope(self):
	self.scope_chooser._radio_buttons.SetSelection(0)
	self.setScopePoint('USRP')

    def setUHDCarrierOffset(self, arg):
	self._uhd_carrier_offset = float(arg)
	self.retune()

    def rxCallback(self):
	print "GOT A PACKET"

    def retune(self):
	up_freq = self._dssdr_channels[self._ccsds_channel][0]
	down_freq = self._dssdr_channels[self._ccsds_channel][1]
	if self.options.test == False and self.options.fromfile == False and self.options.frombitlog == False:
		self._tune_request = uhd.tune_request(down_freq-self._dssdr_mixer_freq+self._if_freq, self._uhd_carrier_offset)
		self.u.set_center_freq(self._tune_request)
	if self.options.test == False and self.options.tofile == False and self.options.tonull == False:
		self._tune_request = uhd.tune_request(self._dssdr_mixer_freq-up_freq+self._if_freq, self._uhd_carrier_offset)
		self.u_tx.set_center_freq(self._tune_request)
	#TODO: Implement LDO logic!
	#self.ldo.set_ref_freq(self.ref_freq)
	#self.ldo.tune(self._dssdr_mixer_freq)
	#self.u_tx.set_center_freq(self._dssdr_mixer_freq-up_freq)
	#self.u_rx.set_center_freq(down_freq-self._dssdr_mixer_freq)

    def commandListener(self):
	while 1:
		cmdfile = file(self.options.read_fifo,"r")
		for s in cmdfile:
			args = s.split()
			if args[0] in self.param_setters:
				self.param_setters[args[0]](args[1])
				sendCommandReply("DSSDR: OK")
			else:
				sendCommandReply("DSSDR: Invalid command")

    def sendCommandReply(self, message):
	replyfile = file(self.options.write_fifo,"w")
	replyfile.write(message)
	replyfile.close()

    def setComplexScopeStyle(self, scope_style):
	self.lock()
	if scope_style == 'FFT':
		self._scope_is_fft = True
	else:
		self._scope_is_fft = False
	self.scopeBlock(self._current_scoped_block,self._current_scoped_block_port)
	self.unlock()

    def setScopePoint(self,point):
	self.lock()
	#Set sample rate depending on where we're scoping
	self._scope_sample_rate = self._down_samples_per_second

	if point == 'USRP':
		self.scopeBlock(self.u, 0)
	elif point == 'Carrier Tracking':
		self.scopeBlock(self.carrier_tracking, 0)
	elif point == 'Sub-Carrier Costas':
		self.scopeBlock(self.subcarrier_costas, 0)
	elif point == 'Sub-Carrier Sync':
		self.scopeBlock(self.subcarrier_sync, 0)
	elif point == 'Data Sync':
		self.scopeBlock(self.data_sync, 0)

	self.unlock()

    def setChannel(self,arg):
	self._ccsds_channel = int(arg)
	self.retune()

    def setLOFreq(self,arg):
	self._dssdr_mixer_freq = float(arg)
	self.retune()

    def setRefFreq(self,arg):
	self.ref_freq = float(arg)
	self.retune()

    def setTurnMult(self,arg):
	self._turn_mult = int(arg)
	self.retune()

    def setTurnDiv(self,arg):
	self._turn_div = int(arg)
	self.retune()

    def setUpGain(self,arg):
	if self.options.test == False and self.options.tofile == False and self.options.tonull == False:
		self.u_tx.set_gain(float(arg))

    def setDownGain(self,arg):
	if self.options.test == False and self.options.fromfile == False and self.options.frombitlog == False:
		self.u.set_gain(float(arg))

    def scopeBlock(self,block_to_scope,port):
	sizeof_stream = block_to_scope.output_signature().sizeof_stream_item(port)
	self._current_scoped_block = block_to_scope
	self._current_scoped_block_port = port
	#self.lock()
	#if self.initialized == True and self.options.fromfile == False and self.options.frombitlog == False:
	#	self.u.stop()
	if self._current_scope_block == self.constellation_scope:
		self.disconnect(self.constellation_scope)
		self.nb0.GetPage(0).GetWin()._box.Hide(self.constellation_scope.win)
	elif self._current_scope_block == self.time_scope:
		self.disconnect(self.time_scope)
		self.nb0.GetPage(0).GetWin()._box.Hide(self.time_scope.win)
	elif self._current_scope_block == self.fft_scope:
		self.disconnect(self.fft_scope)
		self.nb0.GetPage(0).GetWin()._box.Hide(self.fft_scope.win)
	if self.options.disable_viewer != True:
		if sizeof_stream == gr.sizeof_gr_complex:
			#Stream will either be going to constellation sink or FFT
			if self._scope_is_fft:
				self.connect((block_to_scope,port), self.fft_scope)
				self.nb0.GetPage(0).GetWin()._box.Show(self.fft_scope.win)
				self._current_scope_block = self.fft_scope
			else:
				self.connect((block_to_scope,port), self.constellation_scope)
				self.nb0.GetPage(0).GetWin()._box.Show(self.constellation_scope.win)
				self._current_scope_block = self.constellation_scope
		else:
			#Must be a float stream... could actually check it...
			self.connect((block_to_scope,port), self.time_scope)
			self.nb0.GetPage(0).GetWin()._box.Show(self.time_scope.win)
			self._current_scope_block = self.time_scope
		self._current_scope_block.set_sample_rate(self._scope_sample_rate)
	self.nb0.GetPage(0).GetWin()._box.Layout()
	#if self.initialized == True and self.options.fromfile == False and self.options.frombitlog == False:
	#	self.u.start()
	#self.unlock()

    def freqSweep(self,arg):
	self._sweep_profile_times, self._sweep_profile_freqs = sweep_profile_reader.readSweepProfile(arg)
	self.sweep_gen.setProfile(self._sweep_profile_times, self._sweep_profile_freqs)
	self.sweep_gen.sweep()

    def txData(self,arg):
	self._tx_data = eval("'" + arg + "'")
	msg = gr.message_from_string(self._tx_data)
	self.pkt_gen_msgq.insert_tail(msg)

    def setUpBitrate(self,arg):
	self._up_bitrate = float(arg)
	self._up_samples_per_symbol = self._up_samples_per_second/self._up_bitrate
	self.pkt_gen.setInterpRatio(self._up_samples_per_symbol);

    def setDownBitrate(self,arg):
	#if self.options.graphics == True:
	#	self.resetScope()
	#We have to delete the timing recovery block and start again because clock_sync implementation is a kludge
	self._down_bitrate = float(arg)
	self._samples_per_symbol = self._down_samples_per_second/self._down_bitrate
	self.tm_framer.setSampleRate(self._down_bitrate)

	self.data_sync.set_max_freq(self._down_bitrate/self._down_samples_per_second*1.001*2*math.pi)
	self.data_sync.set_min_freq(self._down_bitrate/self._down_samples_per_second*0.999*2*math.pi)
	self.data_sync.set_frequency(self._down_bitrate/self._down_samples_per_second)

    def setUpSPS(self,arg):
	self.sps_tx = float(arg)
	self.u_tx.set_samp_rate(self.sps_tx*self.bitrate_tx)
	#reflect these changes by modifying associated blocks in TX chain

    def setDownSPS(self,arg):
	self.sps_rx = float(arg)
	self.u_rx.set_samp_rate(self.sps_rx*self.bitrate_rx)
	#reflect these changes by modifying associated blocks in RX chain

    def setUpSubFreq(self,arg):
	self._up_sub_freq = float(arg)
	self.subcarrier_mixer_source_tx.set_frequency(self._up_sub_freq)
	self.turnaround_mixer_source.set_frequency(self._up_sub_freq)

    def setDownSubFreq(self,arg):
	self._down_sub_freq = float(arg)
	self.subcarrier_sync.set_max_freq(2*self._down_sub_freq/self._down_samples_per_second*1.0001*2*math.pi)
	self.subcarrier_sync.set_min_freq(2*self._down_sub_freq/self._down_samples_per_second*0.9999*2*math.pi)
	self.subcarrier_sync.set_frequency(2*self._down_sub_freq/self._down_samples_per_second)

    def dopplerReport(self,arg):
	#call doppler report frequency setting member function
	return True

    def rangePN(self,arg):
	#call range report frequency setting member function
	args = arg.split()
	self.pn_range_tx.queueRanging(args[0], args[1], args[2], args[3], args[4], args[5])
	self.pn_range_rx.queueRanging(args[0], args[6], args[7], args[3], args[4], args[5])
	return True

    def rangeSequential(self,arg):
	args = arg.split()
	self.sequential_range_tx.queueSequence(args[0], args[1], args[2], args[3], args[4], args[5], args[6], args[7])
	self.sequential_range_rx.queueSequene(args[0], args[8], args[9], args[2], args[3], args[4], args[5], args[6], args[7])
	return True

    def getASMPattern(self, coding_method):
	if coding_method == 'None':
		asm_pattern = '\x1A\xCF\xFC\x1D'
	elif coding_method == 'CONV':
		asm_pattern = '\x1A\xCF\xFC\x1D'
	elif coding_method == 'RS':
		asm_pattern = '\x1A\xCF\xFC\x1D'
	elif coding_method == 'CC':
		asm_pattern = '\x1A\xCF\xFC\x1D'
	elif coding_method == 'Turbo 1/2':
		asm_pattern = '\x03\x47\x76\xC7\x27\x28\x95\xB0'
	elif coding_method == 'Turbo 1/3':
		asm_pattern = '\x25\xD5\xC0\xCE\x89\x90\xF6\xC9\x46\x1B\xF7\x9C'
	elif coding_method == 'Turbo 1/4':
		asm_pattern = '\x03\x47\x76\xC7\x27\x28\x95\xB0\xFC\xB8\x89\x38\xD8\xD7\x6A\x4F'
	elif coding_method == 'Turbo 1/6':
		asm_pattern = '\x25\xD5\xC0\xCE\x89\x90\xF6\xC9\x46\x1B\xF7\x9C\xDA\x2A\x3F\x31\x76\x6F\x09\x36\xB9\xE4\x08\x63'
	elif coding_method == 'LDPC 7/8':
		asm_pattern = '\x03\x47\x76\xC7\x27\x28\x95\xB0'
	elif coding_method == 'LDPC 1/2' or coding_method == 'LDPC 2/3' or coding_method == 'LDPC 4/5':
		asm_pattern = '\x25\xD5\xC0\xCE\x89\x90\xF6\xC9\x46\x1B\xF7\x9C'
	return asm_pattern

    def setASMThreshold(self,arg):
	self._asm_threshold = int(arg)
	self.soft_correlator.set_threshold(self._asm_threshold)

    def setDownCodingMethod(self,arg):
	self._coding_method = arg
	self.asm_pattern = self.getASMPattern(self._coding_method)
	self.soft_correlator.set_access_code(conv_packed_binary_string_to_1_0_string(self.asm_pattern))
	self.tm_framer.setCodingMethod(self._coding_method)

    def setUpCodingMethod(self,arg):
	self._up_coding_method = arg
	self.up_asm_pattern = self.getASMPattern(self._up_coding_method)
	self.pkt_gen.setCodingMethod(self._up_coding_method)
	self.pkt_gen.setAccessCode(self.up_asm_pattern)

    def setUpSubcarrier(self,arg):
	self._up_subcarrier = arg
	if self._up_subcarrier == 'Square':
		self.subcarrier_mixer_source_tx.set_waveform(analog.GR_SQR_WAVE)
		self.subcarrier_mixer_source_tx.set_amplitude(2.0)
		self.subcarrier_mixer_source_tx.set_offset(-1.0)
	else:
		self.subcarrier_mixer_source_tx.set_waveform(analog.GR_SIN_WAVE)
		self.subcarrier_mixer_source_tx.set_amplitude(1.0)
		self.subcarrier_mixer_source_tx.set_offset(0.0)

    def setConvR(self,arg):
	return True

    def setRSE(self,arg):
	return True

    def setRSI(self,arg):
	self._rs_i = int(arg)
	self.tm_framer.setCodingParameter('I',str(self._rs_i))
	return True

    def setRSQ(self,arg):
	return True

    def setTurboR(self,arg):
	self._down_coding_rate = arg
	return True

    def setTurboK(self,arg):
	return True

    def setLDPCR(self,arg):
	return True

    def setLDPCK(self,arg):
	return True

    def setTMLen(self,arg):
	self._tm_len = int(arg)
	self.tm_framer.setFrameLength(self._tm_len)

    def setUpTMLen(self,arg):
	self._up_tm_len = int(arg)
	self.pkt_gen.setFrameLength(self._up_tm_len)

    def setSampRate(self,arg):
	self._samples_per_second = float(arg)
	self._down_samples_per_second = self._scope_sample_rate = self._samples_per_second/self._down_decim
	self._samples_per_symbol = self._samples_per_second/self._down_decim/self._down_bitrate
	#self.subcarrier_mixer_source_rx.set_sampling_freq(self._samples_per_second)
	if self.options.test == False and self.options.fromfile == False and self.options.frombitlog == False:
		self.u.set_samp_rate(self._samples_per_second)

# /////////////////////////////////////////////////////////////////////////////
#                                   main
# /////////////////////////////////////////////////////////////////////////////

global n_rcvd, n_right

def main():

	_def_excess_bw = 0.35
	_def_freq_bw = 0.001
	_def_timing_bw = 2*math.pi/100.0
	_def_phase_bw = 2*math.pi/100.0
	demods = digital.modulation_utils.type_1_demods()
	
	# Create Options Parser:
	parser = OptionParser (option_class=eng_option, conflict_handler="resolve")
	expert_grp = parser.add_option_group("Expert")
	
	parser.add_option("-m", "--modulation", type="choice", choices=demods.keys(), 
			default='psk',
			help="Select modulation from: %s [default=%%default]" % (', '.join(demods.keys()),))
	parser.add_option("", "--coding-method", type="string", default="None",
			help="downlink coding method [default=%default]")
        parser.add_option("-a", "--args", type="string", default="fpga=usrp_b200_dssdr.bin",
                          help="UHD device address args [default=%default]")
	parser.add_option("","--test", action="store_true", default=False,
			help="specify test (make TCP socket server instead of USRP)")
	parser.add_option("","--down-randomizer-en", action="store_true", default=False,
			help="enable downlink randomizer")
	parser.add_option("","--graphics", action="store_true", default=False,
			help="enable graphics")
	parser.add_option("","--fromfile", action="store_true", default=False,
			help="read iq data from file")
	parser.add_option("","--tofile", action="store_true", default=False,
			help="store iq data to file")
	parser.add_option("","--tonull", action="store_true", default=False,
			help="ignore all TX data")
	parser.add_option("","--read_fifo", default=None,
			help="FIFO to read commands from (for interfacing to GNURadio)")
	parser.add_option("","--write_fifo", default=None,
			help="FIFO to write command responses to (for interfacing to GNURadio)")
	parser.add_option("", "--rx-freq", type="eng_float", default=7.2e9,
			help="set RX frequency [default=%default]")
	parser.add_option("", "--excess-bw", type="float", default=_def_excess_bw,
			help="set RRC excess bandwith factor [default=%default]")
	parser.add_option("", "--freq-bw", type="float", default=_def_freq_bw,
			help="set frequency lock loop lock-in bandwidth [default=%default]")
	parser.add_option("", "--phase-bw", type="float", default=_def_phase_bw,
			help="set phase tracking loop lock-in bandwidth [default=%default]")
	parser.add_option("", "--timing-bw", type="float", default=_def_timing_bw,
			help="set timing symbol sync loop gain lock-in bandwidth [default=%default]")
	parser.add_option("-r", "--bitrate", type="eng_float", default=1000,
			help="specify bitrate [default=%default].")
	parser.add_option("", "--up-bitrate", type="eng_float", default=1000,
			help="specify uplink bitrate [default=%default].")
	parser.add_option("-S", "--samples-per-symbol", type="float", default=2,
			help="set samples/symbol [default=%default]")
	parser.add_option("", "--chbw-factor", type="float", default=1.0,
			help="Channel bandwidth = chbw_factor x signal bandwidth [defaut=%default]")
	parser.add_option("", "--acq_samples", type="eng_float", default=2e6,
			help="Number of samples for frequency acquisition [defaut=%default]")
	parser.add_option("","--bitlog", action="store_true", default=False,
			help="store raw data to file")
	parser.add_option("","--frombitlog", action="store_true", default=False,
			help="read raw data from file")
	parser.add_option("","--debug-pps", action="store_true", default=False,
			help="write pps messages to stdout")
	parser.add_option("","--disable-viewer", action="store_true", default=False,
			help="disable constellation/fft viewer")
	parser.add_option("","--ignore-ntp", action="store_true", default=False,
			help="disable NTP during time sync")
	parser.add_option("", "--rf-freq", type="eng_float", default=8.12e9,
			help="set RF frequency pre-downconversion [default=%default]")
	parser.add_option("", "--if-freq", type="eng_float", default=0,
			help="set IF frequency [default=%default]")
	
	(options, args) = parser.parse_args ()
	
	if len(args) != 0:
		parser.print_help(sys.stderr)
		sys.exit(1)
	
	# build the graph
	tb = my_top_block(options)
	tb.setupFlowgraph()
	if options.graphics == True:
		tb.resetScope()
	
	#r = gr.enable_realtime_scheduling()
	#if r != gr.RT_OK:
	#	print "Warning: Failed to enable realtime scheduling."
	
	tb.Start(True,1000000)        # start flow graph
	tb.Wait()         # wait for it to finish

if __name__ == '__main__':
	#print 'Blocked waiting for GDB attach (pid = %d)' % (os.getpid(),)
	#raw_input('Press Enter to continue: ')
	try:
		main()
	except KeyboardInterrupt:
		pass
