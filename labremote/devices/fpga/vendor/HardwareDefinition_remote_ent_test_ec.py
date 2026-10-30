# -*- coding: utf-8 -*-
"""
Created on Wed Feb  7 07:59:12 2018

@author: 1109282

According to the given mapping, we will add alias for each pin
"""

from labremote.devices.fpga.vendor.HardwareDefinition_v4_04 import *

# Input port pin mapping
# For input pin, there will be only one driver
input_mapping = {'jb_0': 'PMTA', 'jb_2': 'PMTC', 'ja_2': 'SYNC','jb_4': 'PMTFC', 'jb_6': 'PMTFA'}

# Output port pin mapping
# For output pin, there might be more than one device controlled by the output pin
output_mapping = {'TRIG'    : 'ja_4',
                  'AOMC'    : 'ja_3',
                  'EOM_7GC1': 'ja_0',
                  'EOM_7GC2': 'ja_1',
                  'EOM_2GC' : 'jb_7',                  
                  'AOMA'    : 'ja_5',
                  'EOM_7GA1': 'jb_3',
                  'EOM_7GA2': 'jb_5',
                  'EOM_2GA' : 'jb_1',
                  'MW_A'    : 'ja_7',
                  'MW_C'    : 'ja_6',
                  'AOMB'    : 'jc_1',
                  'AOMM'    : 'jc_4',
                  'CCD_EC'  : 'jc_6',
                  'CCD_EA'  : 'jc_3'}
#'EOM_7GA1': 'jb_3', AFTER TEST YOU NEED TO CHANGE THIS VALUE
# Output port configuration
C1_phase_shifter_port = 2
C2_phase_shifter_port = 3


var_dict = globals()
var_list = list(var_dict.keys())

for each_var in var_list:
    for (pin_name, mapping_name) in input_mapping.items():
        pin_name += '_'
        mapping_name += '_'
        index_found = each_var.find(pin_name)
        if index_found == -1:
            continue
        if index_found != 0:
            print('There is a variable (%s) whose name contains %s in the middle' \
                  % (each_var, pin_name))
            continue
        new_var_name = mapping_name + each_var[len(pin_name):]
        var_dict[new_var_name] = var_dict[each_var]

    for (mapping_name, pin_name) in output_mapping.items():
        pin_name += '_'
        mapping_name += '_'
        index_found = each_var.find(pin_name)
        if index_found == -1:
            continue
        if index_found != 0:
            print('There is a variable (%s) whose name contains %s in the middle' \
                  % (each_var, pin_name))
            continue
        new_var_name = mapping_name + each_var[len(pin_name):]
        var_dict[new_var_name] = var_dict[each_var]
    
    
    