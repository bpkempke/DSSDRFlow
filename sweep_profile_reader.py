#!/usr/bin/env python
#
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

def readSweepProfile(profile_name):
	#Construct the expected filename corresponding to this profile name
	profile_filename = 'sweep_profiles/' + profile_name + '.sw'

	#Time and frequency arrays for profile return
	profile_times = []
	profile_freqs = []

	#Brute force profile reading
	for line in open(profile_filename):
		cur_row = line.split()
		profile_times.append(float(cur_row[0]))
		profile_freqs.append(float(cur_row[1]))

	#Return the parsed sweep profile
	return (profile_times, profile_freqs)

if __name__ == '__main__':
	#Test out readSweepProfile
	profile_times, profile_freqs = readSweepProfile('rf2_1')

	#Print out the parsed sweep profile to make sure it makes sense!
	for idx in range(len(profile_times)):
		print str(profile_times[idx]) + ", " + str(profile_freqs[idx])
