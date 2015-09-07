# Copyright 2015 Benjamin Kempke
# 
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
# 
#        http://www.apache.org/licenses/LICENSE-2.0
# 
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

USER_REG_ID = 210
USER_REG_ADF_CLK = 0x00000001
USER_REG_ADF_DAT = 0x00000002
USER_REG_ADF_LE  = 0x00000004
USER_REG_IF_SEL0 = 0x00000008
USER_REG_IF_SEL1 = 0x00000010
USER_REG_REF_SEL = 0x00000020
USER_REG_PPS_SEL = 0x00000040

class dssdrFrontendInterface():

	def __init__(self, usrp):
		self.usrp = usrp
		self.user_reg_static = 0
		self.tuneTo8120()
		self.selectIF(0)
		self.selectRef(1)
		self.selectPPS(1)

	def selectIF(self, if_sel):
		if(if_sel == 0):
			self.user_reg_static &= ~USER_REG_IF_SEL1
			self.user_reg_static |= USER_REG_IF_SEL0
		else:
			self.user_reg_static &= ~USER_REG_IF_SEL0
			self.user_reg_static |= USER_REG_IF_SEL1
		self.usrp.set_user_register(USER_REG_ID, self.user_reg_static)

	def selectRef(self, ref_sel):
		if(ref_sel == 0):
			self.user_reg_static &= ~USER_REG_REF_SEL
		else:
			self.user_reg_static |= USER_REG_REF_SEL
		self.usrp.set_user_register(USER_REG_ID, self.user_reg_static)

	def selectPPS(self, pps_sel):
		if(pps_sel == 0):
			self.user_reg_static &= ~USER_REG_PPS_SEL
		else:
			self.user_reg_static |= USER_REG_PPS_SEL
		self.usrp.set_user_register(USER_REG_ID, self.user_reg_static)

	def tuneTo8120(self):
		self.write4159Reg(0x00000007)
		self.write4159Reg(0x00000006)
		self.write4159Reg(0x00800006)
		self.write4159Reg(0x00000005)
		self.write4159Reg(0x00800005)
		self.write4159Reg(0x00180004)
		self.write4159Reg(0x00180044)
		self.write4159Reg(0x00820003)
		self.write4159Reg(0x07008002)
		self.write4159Reg(0x00000009)
		self.write4159Reg(0x30CB0000)
	
	def write4159Reg(self, reg):
		#Clear contents of register to start
		self.usrp.set_user_register(USER_REG_ID, self.user_reg_static | 0)
	
		for bit_idx in range(32):
			cur_bit = reg & 0x80000000
			if cur_bit > 0:
				cur_bit = 1
			self.usrp.set_user_register(USER_REG_ID, self.user_reg_static | (cur_bit << 1))
			self.usrp.set_user_register(USER_REG_ID, self.user_reg_static | ((cur_bit << 1) | 1))
			self.usrp.set_user_register(USER_REG_ID, self.user_reg_static | (cur_bit << 1))
			reg = reg << 1
	
		#Latch contents of register now that it's all clocked in
		self.usrp.set_user_register(USER_REG_ID, self.user_reg_static | 0)
		self.usrp.set_user_register(USER_REG_ID, self.user_reg_static | 4)
		self.usrp.set_user_register(USER_REG_ID, self.user_reg_static | 0)
