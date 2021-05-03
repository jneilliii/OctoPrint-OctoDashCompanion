# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
import octoprint.filemanager.util
from octoprint.filemanager import FileDestinations
from octoprint.util.paths import normalize
from octoprint.events import Events
from octoprint.util import dict_merge
import os
import sys
import shutil
import json


class OctodashcompanionPlugin(octoprint.plugin.SettingsPlugin,
							  octoprint.plugin.AssetPlugin,
							  octoprint.plugin.TemplatePlugin,
							  octoprint.plugin.EventHandlerPlugin):

	def __init__(self):
		self.config_file = normalize("{}/config.json".format(_default_configdir("octodash")))

	# ~~ SettingsPlugin mixin

	def get_settings_defaults(self):
		return dict(
			config_directory=normalize(_default_configdir("octodash"))
		)

	def on_settings_load(self):
		self._logger.info("attempting open of {}.".format(self.config_file))
		with open(self.config_file) as file:
			config_file_json = json.load(file)
		self._logger.info("loaded data from {}: {}".format(self.config_file, config_file_json))
		if config_file_json is not None:
			config_file_json["config_directory"] = self.config_file
			return config_file_json
		else:
			self._logger.info("unable to open {} returning default settings.".format(self.config_file))
			return self.get_settings_defaults()

	def on_settings_save(self, data):
		self._logger.info("settings received: {}".format(data))
		# build our settings up that are to persist in octoprint's settings
		# currently it doesn't really do anything because the config_directory setting
		# is not exposed as an editable field in settings, and don't think it needs
		# to be?
		settings_to_save = {}
		if data.get("config_directory"):
			settings_to_save["config_directory"] = data.get("config_directory")

		if settings_to_save != {}:
			self._logger.info("saving settings: {}".format(settings_to_save))
			octoprint.plugin.SettingsPlugin.on_settings_save(self, settings_to_save)

		# save changes to config.json in config_directory
		if data.get("config"):
			self._logger.info("merging settings to {}: {}".format(self.config_file, {"config": data.get("config")}))
			with open(self.config_file, "r") as old_settings_file:
				config_file_json = json.load(old_settings_file)
				config_to_save = dict_merge(config_file_json, {"config": data.get("config")})
			with open(self.config_file, "w") as new_settings_file:
				json.dump(config_to_save, new_settings_file, indent="\t")

	def on_event(self, event, payload):
		if event == Events.UPLOAD:
			if payload["target"] == "local" and payload["path"] == "custom-styles.css":
				source_file = self._file_manager.sanitize_path(FileDestinations.LOCAL, payload["path"])
				destination_file = normalize("{}/custom-styles.css".format(self._settings.get(["config_directory"])))
				self._logger.info("attempting copy of {} to {}".format(source_file, destination_file))
				shutil.copyfile(source_file, destination_file)
				self._logger.info("attempting removal of {}".format(source_file))
				self._file_manager.remove_file(FileDestinations.LOCAL, payload["path"])

	# ~~ AssetPlugin mixin

	def get_assets(self):
		return dict(
			js=["js/fontawesome-iconpicker.min.js", "js/ko.iconpicker.js", "js/octodashcompanion.js"],
			css=["css/fontawesome-iconpicker.min.css", "css/octodashcompanion.css"]
		)

	# ~~ TemplatePlugin mixin

	def get_template_configs(self):
		return [dict(type="settings", custom_bindings=True)]

	def get_template_vars(self):
		return {"plugin_version": self._plugin_version}

	# ~~ extension_tree hook

	def get_extension_tree(self, *args, **kwargs):
		return dict(
			machinecode=dict(
				octodashcompanion=["css"]
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
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
		"octoprint.filemanager.extension_tree": __plugin_implementation__.get_extension_tree,
	}
