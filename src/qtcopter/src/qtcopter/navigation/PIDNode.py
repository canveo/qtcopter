#!/usr/bin/env python
# Software License Agreement (BSD License)

import rospy
import os;
import sys;
from qtcopter.srv import *
from qtcopter.msg import controller_msg, uav_msg
from PIDModule import PIDController
import Configuration

#=================================================
#Configuration file for all PID relevant data
#=================================================
config = Configuration.Configuration(os.getcwd()+'/PidConfig.json')

#=================================================
#PIDManager class
#Responsible for initiating all channels PID controllers
#Provide callbacks for updating gains and starting/stopping the PID updates publishing
#Publish PID updates in constant "Rate" taken from configuration file
#=================================================
class PIDManager:
    #=================================================
    #PIDManager ctor
    #Creates a PIDController object for X,Y,Z and Theta channels
    #Start PID IsRunnig state to False (PID is not running until requested by a service
    #Subscribe on ros /pid_input channel to collect new error data
    #Publishes /pid/controller_command channel with corrections on last known errors
    #register 2 control services:
    #   /pid_control, type PidControlSrv which get True/False value for starting/stopping the PID publishing
    #   /pid_set_axis_gains, type UpdateGainsSrv which get ki,kd,kp,channel which updates the channel gains
    #=================================================
    def __init__(self, dt, normalizationFactor):
        rospy.loginfo("initiatin PIDManager class")
        try:
            #Read configuration from config file
            xConfig = config.GetConfigurationSection("X")
            yConfig = config.GetConfigurationSection("Y")
            zConfig = config.GetConfigurationSection("Z")
            thetaConfig = config.GetConfigurationSection("Theta")

            #Create PID controller objects
            self.AxisControllers = {
                "X": PIDController(xConfig["KP"], xConfig["KD"], xConfig["KI"], dt, xConfig["MinLimit"], xConfig["MaxLimit"], xConfig["NValue"], normalizationFactor, "X"),
                "Y": PIDController(yConfig["KP"], yConfig["KD"], yConfig["KI"], dt, yConfig["MinLimit"], yConfig["MaxLimit"], yConfig["NValue"], normalizationFactor, "Y"),
                "Z": PIDController(zConfig["KP"], zConfig["KD"], zConfig["KI"], dt, zConfig["MinLimit"], zConfig["MaxLimit"], zConfig["NValue"], normalizationFactor, "Z"),
                "Theta": PIDController(thetaConfig["KP"], thetaConfig["KD"], thetaConfig["KI"], dt, thetaConfig["MinLimit"], thetaConfig["MaxLimit"],thetaConfig["NValue"], normalizationFactor, "T")
                }

            #Set Properties
            self.IsRunning = False
            self.dt=dt
            self.normalizationFactor = normalizationFactor
            self.message = controller_msg()

            #Topics & Services registration
            rospy.Subscriber("/pid_input", controller_msg, self.DataCollector)
            self.PidOutputTopic = rospy.Publisher('/pid/controller_command', controller_msg,queue_size=1)
            self.PidControlService = rospy.Service('/pid_control', PidControlSrv, self.PIDControlServiceRequestHandler)
            self.UpdateAxisConstantsService = rospy.Service('/pid_set_axis_gains', UpdateGainsSrv, self.UpdateAxisGainsRequestHandler)
            self.UpdateAllAxisGainsService = rospy.Service('/pid_set_all_gains', AllGainsSrv, self.SetAllGainsHandler)
        except:
            rospy.logerr("An error occured initiatin PIDManager class: {0} ".format(sys.exc_info()))

    #================================================================
    #DataCollector Callback
    #used for updating error on each axis from /pid_input topic
    #This callback is expected to run at about "Rate" times a second
    #================================================================
    def DataCollector(self, msg):
        self.AxisControllers["X"].SetError(msg.x)
        self.AxisControllers["Y"].SetError(msg.y)
        self.AxisControllers["Z"].SetError(msg.z)
        self.AxisControllers["Theta"].SetError(msg.t)
    #======================================================================
    #Run method
    #This is the main responsibility of this class
    #If IsRunnig is false, nothing would happen and no calculations occurs
    #This is done for better performance
    #Otherwise:
    #Run gets called "Rate" times a second
    #Request a fix on each channel
    #and publish the fixes to the PidOutputTopic
    #Note: Due to "Rate", no logging is provided here
    #======================================================================
    def Run(self):
        if self.IsRunning:
            self.message.x = float(self.AxisControllers["X"].GetFix())
            self.message.z = float(self.AxisControllers["Z"].GetFix())
            self.message.y = float(self.AxisControllers["Y"].GetFix())
            self.message.t = float(self.AxisControllers["Theta"].GetFix())
            self.PidOutputTopic.publish(self.message)

    #======================================================================
    #PIDControlServiceRequestHandler
    #Service handler for starting/stopping publishing on PID
    #Service gets a PidControlSrv request type
    #and updates IsRunning depended on IsRunning != request.state
    #======================================================================
    def PIDControlServiceRequestHandler(self, req):
        rospy.loginfo("PidControlService request - requested running: {0}".format(req.state))
        if not self.IsRunning == req.state:
            self.IsRunning = req.state
            rospy.loginfo("PID IsRunning set to: {0}".format(self.IsRunning))
        else:
            rospy.loginfo("PID IsRunning state wasn't changed, it was already as requested")
        return PidControlSrvResponse(self.IsRunning)

    #======================================================================
    #updateAxisGainsRequestHandler
    #Service handler for updating gains on a specific channel
    #service get a UpdateGainsSrv request type
    #Service will verify request.channel is either X,Y,Z or Theta
    #   Otherwise, False is returned and no update occurs
    #If request.channel is any of the above,
    #a new PIDController is created with the new gains and old min/max/dt/normaliztionFactor values
    #in order to update the PID manager, it would be stopped if running, controller is swapped and
    #then returned to previous state (running or stopped)
    #True is returned on success, False otherwise
    #======================================================================
    def UpdateAxisGainsRequestHandler(self, req):
        if req.channel != 'X' and req.channel != 'Y' and req.channel != 'Z' and req.channel != 'Theta':
            rospy.logerr("Invalid channel name was provided")
            return UpdateGainsSrvResponse(False)
        try:
            rospy.loginfo("UpdateAxisGains request for: {0}".format(req.channel))
            rospy.loginfo("New values are (Kp,Kd,Ki): {0} {1} {2}".format(req.kp,req.kd,req.ki))
            minLimit = self.AxisControllers[req.channel].MinLimit
            maxLimit = self.AxisControllers[req.channel].MaxLimit
            nValue = self.AxisControllers[req.channel].nValue
            controller = PIDController(req.kp,req.kd, req.ki,self.dt,minLimit,maxLimit, nValue,self.normalizationFactor, req.channel)
            isRunning = self.IsRunning
            if isRunning:
                self.IsRunning = False
            self.AxisControllers[req.channel] = controller
            self.IsRunning = isRunning
            return UpdateGainsSrvResponse(True)
        except:
            rospy.logerr("There was an error {0}".format(sys.exc_info()[0]))
            return UpdateGainsSrvResponse(False)

    #======================================================================
    #SetAllGainsHandler
    #Service handler for updating gains on all channels
    #and allow resetting the integral part of all channels
    #======================================================================
    def SetAllGainsHandler(self, req):
        rospy.loginfo("Set all gains request received")
        #X gains
        minLimit = self.AxisControllers['X'].MinLimit
        maxLimit = self.AxisControllers['X'].MaxLimit
        nValue = self.AxisControllers['X'].nValue
        xCtrl = PIDController(req.xkp, req.xkd, req.xki,self.dt,minLimit,maxLimit, nValue,self.normalizationFactor, 'X')

        #Y gains
        minLimit = self.AxisControllers['Y'].MinLimit
        maxLimit = self.AxisControllers['Y'].MaxLimit
        nValue = self.AxisControllers['Y'].nValue
        yCtrl = PIDController(req.ykp, req.ykd, req.yki,self.dt,minLimit,maxLimit, nValue,self.normalizationFactor, 'Y')

        #Z gains
        minLimit = self.AxisControllers['Z'].MinLimit
        maxLimit = self.AxisControllers['Z'].MaxLimit
        nValue = self.AxisControllers['Z'].nValue
        zCtrl = PIDController(req.zkp, req.zkd, req.zki,self.dt,minLimit,maxLimit, nValue,self.normalizationFactor, 'Z')

        #Theta gains
        minLimit = self.AxisControllers['Theta'].MinLimit
        maxLimit = self.AxisControllers['Theta'].MaxLimit
        nValue = self.AxisControllers['Theta'].nValue
        tCtrl = PIDController(req.tkp, req.tkd, req.tki,self.dt,minLimit,maxLimit, nValue,self.normalizationFactor, 'Theta')
        try:
            #Replace controllers
            isRunning = self.IsRunning
            if isRunning:
                self.IsRunning = False
            self.AxisControllers = {
                "X": xCtrl,
                "Y": yCtrl,
                "Z": zCtrl,
                "Theta": tCtrl
                }

            self.IsRunning = isRunning
            rospy.loginfo("New gains were set")
            return AllGainsSrvResponse(True)
        except:
            rospy.logerr("There was an error {0}".format(sys.exc_info()[0]))
            return AllGainsSrvResponse(False)

#======================================================================
#Main routine
#Create a ros node called pid_node
#generate the PIDManager class which handles all logic
#start the run loop for publishing updates and then sleep for "Rate"
#as defined in configuration
#======================================================================
if __name__ == '__main__':
    try:
        rospy.init_node('pid_node')
        rospy.loginfo("Started PID node")
        generalConfig = config.GetConfigurationSection("General")
        pidManager = PIDManager(generalConfig["Rate"], generalConfig["NormalizationFactor"])
        rospy.loginfo("Created all channels PID controllers")
        rate = rospy.Rate((int)(generalConfig["Rate"]))
        while not rospy.is_shutdown():
            pidManager.Run()
            rate.sleep()
    except rospy.ROSInterruptException:
        pass
