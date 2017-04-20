#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (C) 2013-2017, Southwest Research Institute® (SwRI®)
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its contributors
# may be used to endorse or promote products derived from this software without
# specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.


import subprocess
import roslib; roslib.load_manifest('swri_transform_util')
import rospy
import tf
from gps_common.msg import GPSFix
from diagnostic_msgs.msg import DiagnosticArray
from diagnostic_msgs.msg import DiagnosticStatus
from diagnostic_msgs.msg import KeyValue

# Global variables
_gps_fix = None
_local_xy_frame = None

_sub = None
_origin_pub = None

def parse_origin(local_xy_origin):
    global _gps_fix

    local_xy_origins = rospy.get_param('~local_xy_origins', [])

    for origin in local_xy_origins:
        if origin["name"] == local_xy_origin:

            _gps_fix = GPSFix()
            _gps_fix.header.frame_id = _local_xy_frame
            _gps_fix.status.header.frame_id = local_xy_origin
            _gps_fix.latitude = origin["latitude"]
            _gps_fix.longitude = origin["longitude"]
            _gps_fix.altitude = origin["altitude"]
            _gps_fix.track = 90

            _origin_pub.publish(_gps_fix)

    return

def gps_callback(data):
    if data.status.status == -1:
        # This fix is invalid, ignore it and wait until we get a valid one
        rospy.logwarn("Got invalid fix.  Waiting for a valid one...")
        return
    global _gps_fix

    if _gps_fix == None:
        global _sub
        _sub.unregister()
        _sub = None

        _gps_fix = data
        _gps_fix.header.frame_id = _local_xy_frame
        _gps_fix.track = 90

        _origin_pub.publish(_gps_fix)

def gps_diagnostic_callback(data):
    global _gps_fix
    global _too_far_from_origin
    
    if _gps_fix != None:
        # Compare the local_xy_origin gps fix to most recent gps value
        # If difference is greater than 1 deg in lat/lon, we have traveled more than 10Km
        # which will be reported as a warning since our near_field assumptions will fail.
        if abs(data.latitude - _gps_fix.latitude) > 1.0 or abs(data.longitude - _gps_fix.longitude) > 1.0:
          _too_far_from_origin = True
        else:
          _too_far_from_origin = False

def initialize_origin():
    rospy.init_node('initialize_origin', anonymous=True)

    global _origin_pub
    global _local_xy_frame
    global _too_far_from_origin
    _origin_pub = rospy.Publisher('/local_xy_origin', GPSFix, latch=True, queue_size=2)

    diagnostic_pub = rospy.Publisher('/diagnostics', DiagnosticArray, queue_size=2)

    local_xy_origin = rospy.get_param('~local_xy_origin', 'auto')
    _local_xy_frame = rospy.get_param('~local_xy_frame', 'map')
    _local_xy_frame_identity = rospy.get_param('~local_xy_frame_identity', _local_xy_frame + "__identity")
    _too_far_from_origin = False
   
    if local_xy_origin == "auto":
        global _sub
        _sub = rospy.Subscriber("gps", GPSFix, gps_callback)
    else:
        parse_origin(local_xy_origin)
    _gps_diag_sub = rospy.Subscriber("gps", GPSFix, gps_diagnostic_callback)

    if len(_local_xy_frame):
        tf_broadcaster = tf.TransformBroadcaster()
    else:
        tf_broadcaster = None

    hw_id = rospy.get_param('~hw_id', 'none')

    while not rospy.is_shutdown():
        if tf_broadcaster:
            # Publish transform involving map (to an anonymous unused
            # frame) so that TransformManager can support /tf<->/wgs84
            # conversions without requiring additional nodes.
            tf_broadcaster.sendTransform(
                (0, 0, 0),
                (0, 0, 0, 1),
                rospy.Time.now(),
                _local_xy_frame_identity, _local_xy_frame)

        if _gps_fix == None:
            diagnostic = DiagnosticArray()
            diagnostic.header.stamp = rospy.Time.now()

            status = DiagnosticStatus()

            status.name = "LocalXY Origin"
            status.hardware_id = hw_id

            status.level = DiagnosticStatus.ERROR
            status.message = "No Origin"

            diagnostic.status.append(status)

            diagnostic_pub.publish(diagnostic)
        else:
            _origin_pub.publish(_gps_fix) # Publish this at 1Hz for bag convenience
            diagnostic = DiagnosticArray()
            diagnostic.header.stamp = rospy.Time.now()

            status = DiagnosticStatus()

            status.name = "LocalXY Origin"
            status.hardware_id = hw_id


            if local_xy_origin == 'auto':
                status.message = "Has Origin (auto)"
            else:
                status.message = "Origin is static (non-auto)"
            if _too_far_from_origin:
                status.level = DiagnosticStatus.WARN
                status.message += ", but is more than 1deg (~10km) away from current gps fix"
            else:
                status.level = DiagnosticStatus.OK
                    
            value0 = KeyValue()
            value0.key = "Origin"
            value0.value = _gps_fix.status.header.frame_id
            status.values.append(value0)

            value1 = KeyValue()
            value1.key = "Latitude"
            value1.value = "%f" % _gps_fix.latitude
            status.values.append(value1)

            value2 = KeyValue()
            value2.key = "Longitude"
            value2.value = "%f" % _gps_fix.longitude
            status.values.append(value2)

            value3 = KeyValue()
            value3.key = "Altitude"
            value3.value = "%f" % _gps_fix.altitude
            status.values.append(value3)

            diagnostic.status.append(status)

            diagnostic_pub.publish(diagnostic)
        rospy.sleep(1.0)
if __name__ == '__main__':
    try:
        initialize_origin()
    except rospy.ROSInterruptException: pass
