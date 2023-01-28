# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
import octoprint.filemanager.util
from flask_babel import gettext
from octoprint.filemanager import FileDestinations
from octoprint.util.paths import normalize
from octoprint.events import Events
from octoprint.util import dict_merge
from octoprint.access.permissions import Permissions, ADMIN_GROUP
import flask
import os
import sys
import shutil
import json
import re
from datetime import datetime, timezone


class OctodashcompanionPlugin(octoprint.plugin.SettingsPlugin,
							  octoprint.plugin.AssetPlugin,
							  octoprint.plugin.TemplatePlugin,
							  octoprint.plugin.EventHandlerPlugin,
							  octoprint.plugin.BlueprintPlugin,
							  octoprint.plugin.SimpleApiPlugin):

	def __init__(self):
		self.config_file = normalize("{}/config.json".format(_default_configdir("octodash")))
		self.use_received_fan_speeds = False
		self.fan_regex = re.compile("M106 (?:P([0-9]) )?S([0-9]+)")
		self.forced_types = {"plugins": {"tasmota": {"index": "int"}, "tasmotaMqtt": {"relayNumber": "int"},
										 "enclosure": {"ambientSensorID": "int", "filament1SensorID": "int",
													   "filament2SensorID": "int"}}}

	# ~~ SettingsPlugin mixin

	def get_settings_defaults(self):
		return dict(
			config_directory=normalize(_default_configdir("octodash"))
		)

	def on_settings_load(self):
		self._logger.debug("attempting open of {}.".format(self.config_file))
		with open(self.config_file) as file:
			config_file_json = json.load(file)
		self._logger.debug("loaded data from {}".format(self.config_file))
		if config_file_json is not None:
			config_file_json["config_directory"] = self.config_file
			if os.path.exists("{}/config.json".format(self.get_plugin_data_folder())):
				config_file_json["last_backup"] = datetime.fromtimestamp(os.stat("{}/config.json".format(self.get_plugin_data_folder())).st_mtime).strftime("%x %X")
			else:
				config_file_json["last_backup"] = ""
			return config_file_json
		else:
			self._logger.debug("unable to open {} returning default settings.".format(self.config_file))
			return self.get_settings_defaults()

	def on_settings_save(self, data):
		self._logger.debug("settings received: {}".format(data))
		# build our settings up that are to persist in octoprint's settings
		# currently it doesn't really do anything because the config_directory setting
		# is not exposed as an editable field in settings, and don't think it needs
		# to be?
		settings_to_save = {}
		if data.get("config_directory"):
			settings_to_save["config_directory"] = data.get("config_directory")

		if settings_to_save != {}:
			self._logger.debug("saving settings: {}".format(settings_to_save))
			octoprint.plugin.SettingsPlugin.on_settings_save(self, settings_to_save)

		# save changes to config.json in config_directory
		if data.get("config"):
			# type conversions from OP settings, only seems to effect integers.
			new_config_settings = data.get("config")
			for item in new_config_settings:
				if item in self.forced_types:
					sub_items = new_config_settings[item]
					for sub_items_items in sub_items:
						if sub_items_items in self.forced_types[item]:
							for key in sub_items[sub_items_items]:
								if key in self.forced_types[item][sub_items_items]:
									if self.forced_types[item][sub_items_items][key] == "int":
										sub_items[sub_items_items][key] = int(sub_items[sub_items_items][key])
									if self.forced_types[item][sub_items_items][key] == "bool":
										sub_items[sub_items_items][key] = bool(sub_items[sub_items_items][key])
			self._logger.debug(
				"creating backup of {} to {}.bak".format(self.config_file, {"config": new_config_settings}))
			shutil.copyfile(self.config_file, "{}.bak".format(self.config_file))
			self._logger.debug("merging settings to {}: {}".format(self.config_file, {"config": new_config_settings}))
			with open(self.config_file, "r") as old_settings_file:
				config_file_json = json.load(old_settings_file)
				config_to_save = dict_merge(config_file_json, {"config": new_config_settings})
			with open(self.config_file, "w") as new_settings_file:
				json.dump(config_to_save, new_settings_file, indent="\t")

	def on_event(self, event, payload):
		if event == Events.UPLOAD:
			if payload["target"] == "local" and payload["path"] == "custom-styles.css":
				source_file = self._file_manager.sanitize_path(FileDestinations.LOCAL, payload["path"])
				destination_file = normalize("{}/custom-styles.css".format(self._settings.get(["config_directory"])))
				self._logger.debug("attempting copy of {} to {}".format(source_file, destination_file))
				shutil.copyfile(source_file, destination_file)
				self._logger.debug("attempting removal of {}".format(source_file))
				self._file_manager.remove_file(FileDestinations.LOCAL, payload["path"])
			if payload["target"] == "local" and payload["path"] == "config.json":
				source_file = self._file_manager.sanitize_path(FileDestinations.LOCAL, payload["path"])
				destination_file = normalize("{}/config.json".format(self._settings.get(["config_directory"])))
				self._logger.debug("attempting copy of {} to {}".format(source_file, destination_file))
				shutil.copyfile(source_file, destination_file)
				self._logger.debug("attempting removal of {}".format(source_file))
				self._file_manager.remove_file(FileDestinations.LOCAL, payload["path"])
				self._settings.save(force=True, trigger_event=True)

	# ~~ BluePrint routes

	@octoprint.plugin.BlueprintPlugin.route("webcam")
	def webcam_route(self):
		webcam_url = self._settings.global_get(["webcam", "stream"])

		# Anything passed here can be used as {{ variable_name }} in the template
		render_kwargs = {
			"webcam_url": webcam_url
		}

		if self._settings.global_get(["plugins", "multicam"]) and "webcam" in flask.request.values:
			webcam = self._settings.global_get(["plugins", "multicam", "multicam_profiles"])[
				int(flask.request.values["webcam"]) - 1]
			render_kwargs["webcam_url"] = webcam["URL"]
			if webcam["flipH"]:
				render_kwargs["webcam_flip_horizontal"] = "flipH"
			if webcam["flipV"]:
				render_kwargs["webcam_flip_vertical"] = "flipV"
			if webcam["rotate90"]:
				render_kwargs["webcam_rotate_ccw"] = "rotate90"
		else:
			if self._settings.global_get_boolean(["webcam", "flipH"]):
				render_kwargs["webcam_flip_horizontal"] = "flipH"
			if self._settings.global_get_boolean(["webcam", "flipV"]):
				render_kwargs["webcam_flip_vertical"] = "flipV"
			if self._settings.global_get_boolean(["webcam", "rotate90"]):
				render_kwargs["webcam_rotate_ccw"] = "rotate90"
			if self._settings.global_get(["plugins", "multicam"]):
				render_kwargs["webcams"] = self._settings.global_get(["plugins", "multicam", "multicam_profiles"])

		response = flask.make_response(flask.render_template("webcam.jinja2", **render_kwargs))
		response.headers["X-Frame-Options"] = ""
		return response

	@octoprint.plugin.BlueprintPlugin.route("restart")
	def restart_route(self):
		self._logger.debug("Restart OctoDash request received")
		import subprocess
		import shlex
		try:
			subprocess.run(shlex.split("sudo service getty@tty1 restart"))
		except subprocess.CalledProcessError as e:
			self._logger.debug("There was an error attempting to restart OctoDash: {}".format(e))
			return flask.jsonify({"restart": False})
		return flask.jsonify({"restart": True})

	@octoprint.plugin.BlueprintPlugin.route("sleep")
	def sleep_route(self):
		import subprocess
		try:
			sleep_command = self.on_settings_load()["config"]["octodash"]["screenSleepCommand"].split()
			if "xset" in sleep_command and "-display" not in sleep_command:
				sleep_command.extend(["-display", ":0.0"])
			self._logger.debug("Sleep: {}".format(sleep_command))
			subprocess.run(sleep_command)
			render_kwargs = {"sleep": True}
		except Exception as e:
			self._logger.debug("Sleep error: {}".format(e))
			render_kwargs = {"sleep": False, "error": "{}".format(e)}
		response = flask.make_response(flask.render_template("sleep.jinja2", **render_kwargs))
		response.headers["X-Frame-Options"] = ""
		return response

	@octoprint.plugin.BlueprintPlugin.route("switch_instance")
	def switch_instance_route(self):
		instance = flask.request.values.get("url")
		instance_name = flask.request.values.get("name")

		if instance is None:
			flask.abort(400, description="Missing instance url parameter")

		instance_url = "http://{}/".format(instance)

		with open(self.config_file, "r") as old_settings_file:
			config_file_json = json.load(old_settings_file)
			config_to_save = dict_merge(config_file_json, {"config": {"octoprint": {"url": instance_url}, "printer": {"name": instance_name}}})
		with open(self.config_file, "w") as new_settings_file:
			json.dump(config_to_save, new_settings_file, indent="\t")
			self._event_bus.fire(Events.SETTINGS_UPDATED)

		self._logger.debug("Restarting OctoDash due to instance change")
		import subprocess
		import shlex
		try:
			subprocess.run(shlex.split("sudo service getty@tty1 restart"))
		except subprocess.CalledProcessError as e:
			self._logger.debug("There was an error attempting to restart OctoDash: {}".format(e))
			return flask.jsonify({"restart": False, "instance_url": instance_url})

		return flask.jsonify({"instance_url": instance_url})

	def is_blueprint_protected(self):
		return False

	# ~~ Access Permissions Hook

	def get_additional_permissions(self, *args, **kwargs):
		return [
			dict(key="MANAGEBACKUPS",
				 name="Manage Backups",
				 description=gettext("Allow backup and restore of config.json."),
				 roles=["admin"],
				 dangerous=True,
				 default_groups=[ADMIN_GROUP])
		]

	# ~~ SimpleApiPlugin mixin

	def get_api_commands(self):
		return dict(
			backup_config=[],
			restore_config=[]
		)

	def on_api_command(self, command, data):
		if not Permissions.PLUGIN_OCTODASHCOMPANION_MANAGEBACKUPS.can():
			return flask.make_response("Insufficient rights", 403)

		try:
			if command == "backup_config":
				self._logger.debug(
					"Creating backup of {} as {}/config.json".format(self.config_file, self.get_plugin_data_folder()))
				shutil.copyfile(self.config_file, "{}/config.json".format(self.get_plugin_data_folder()))
				return flask.jsonify({"success": True, "last_backup": datetime.fromtimestamp(os.stat("{}/config.json".format(self.get_plugin_data_folder())).st_mtime).strftime("%x %X")})
			if command == "restore_config":
				self._logger.debug(
					"Restoring backup {}/config.json as {}".format(self.get_plugin_data_folder(), self.config_file))
				shutil.copyfile("{}/config.json".format(self.get_plugin_data_folder()), self.config_file)
				return flask.jsonify({"success": True, "last_backup": datetime.fromtimestamp(os.stat("{}/config.json".format(self.get_plugin_data_folder())).st_mtime).strftime("%x %X")})
		except Exception as e:
			return flask.jsonify({"success": False, "error": e.strerror})

	# ~~ AssetPlugin mixin

	def get_assets(self):
		return dict(
			js=["js/jquery-ui.min.js", "js/knockout-sortable.1.2.0.js", "js/fontawesome-iconpicker.min.js",
				"js/ko.iconpicker.js", "js/octodashcompanion.js"],
			css=["css/fontawesome-iconpicker.min.css", "css/octodashcompanion.css"]
		)

	# ~~ TemplatePlugin mixin

	def get_template_configs(self):
		return [dict(type="settings", custom_bindings=True)]

	def get_template_vars(self):
		return {"plugin_version": self._plugin_version}

	# ~~ GCode Received hook

	def process_received_gcode(self, comm, line, *args, **kwargs):
		if "M106" not in line:
			return line

		self.send_fan_speed(line, "received")
		return line

	# ~~ GCode Sent hook

	def process_sent_gcode(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
		if gcode and gcode == "M106" and self.use_received_fan_speeds is False:
			self.send_fan_speed(cmd, "sent")

	def send_fan_speed(self, gcode, direction):
		fan_match = self.fan_regex.match(gcode)
		if fan_match:
			if direction == "received":
				self.use_received_fan_speeds = True
			fan, fan_set_speed = fan_match.groups()
			if fan is None:
				fan = 1
			self._plugin_manager.send_plugin_message("octodash", {
				"fanspeed": {"{}".format(fan): (int("{}".format(fan_set_speed)) / 255 * 100)}})

	# ~~ extension_tree hook

	def get_extension_tree(self, *args, **kwargs):
		return dict(
			machinecode=dict(
				octodashcompanion=["css", "json"]
			)
		)

	# ~~ Softwareupdate hook

	def get_update_information(self):
		return dict(
			octodashcompanion=dict(
				displayName="OctoDash Companion",
				displayVersion=self._plugin_version,

				# version check: github repository
				type="github_release",
				user="jneilliii",
				repo="OctoPrint-OctoDashCompanion",
				current=self._plugin_version,
				stable_branch=dict(
					name="Stable", branch="master", comittish=["master"]
				),
				prerelease_branches=[
					dict(
						name="Release Candidate",
						branch="rc",
						comittish=["rc", "master"],
					)
				],

				# update method: pip
				pip="https://github.com/jneilliii/OctoPrint-OctoDashCompanion/archive/{target_version}.zip"
			)
		)


__plugin_name__ = "OctoDash Companion"
__plugin_pythoncompat__ = ">=3.3,<4"  # only python 3.3+
__plugin_settings_overlay__ = {'system': {'actions': [{'action': 'octodash_start',
													   'command': 'sudo service getty@tty1 start',
													   'name': 'Start OctoDash'},
													  {'action': 'octodash_stop',
													   'command': 'sudo service getty@tty1 stop',
													   'name': 'Stop OctoDash',
													   'confirm': 'You are about to shutdown OctoDash.'},
													  {'action': 'octodash_restart',
													   'command': 'sudo service getty@tty1 restart',
													   'name': 'Restart OctoDash',
													   'confirm': 'You are about to restart OctoDash.'}]}}


def _default_configdir(applicationName):
	# taken from http://stackoverflow.com/questions/1084697/how-do-i-store-desktop-application-data-in-a-cross-platform-way-for-python
	if sys.platform == "darwin":
		import appdirs

		return appdirs.user_data_dir(applicationName, "")
	elif sys.platform == "win32":
		return os.path.join(os.environ["APPDATA"], applicationName)
	else:
		return os.path.expanduser(os.path.join("~", ".config", applicationName.lower()))


def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = OctodashcompanionPlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.comm.protocol.gcode.received": __plugin_implementation__.process_received_gcode,
		"octoprint.comm.protocol.gcode.sent": __plugin_implementation__.process_sent_gcode,
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
		"octoprint.access.permissions": __plugin_implementation__.get_additional_permissions,
		"octoprint.filemanager.extension_tree": __plugin_implementation__.get_extension_tree,
	}
