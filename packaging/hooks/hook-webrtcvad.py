"""本项目使用webrtcvad-wheels发行包；导入模块名称仍为webrtcvad。"""
from PyInstaller.utils.hooks import copy_metadata

datas = copy_metadata('webrtcvad-wheels')
