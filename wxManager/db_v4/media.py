#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
@Time        : 2024/12/12 17:06 
@Author      : SiYuan 
@Email       : 863909694@qq.com 
@File        : MemoTrace-media.py 
@Description : 
"""
import os
import shutil
import subprocess
import traceback

from wxManager.merge import increase_update_data, increase_data
from wxManager.model import DataBaseBase
from wxManager.log import logger


def get_ffmpeg_path():
    configured_path = os.environ.get("FFMPEG_PATH")
    if configured_path and os.path.exists(configured_path):
        return configured_path
    return shutil.which("ffmpeg")


def convert_pcm_to_mp3(pcm_path, mp3_path):
    ffmpeg_path = get_ffmpeg_path()
    if not ffmpeg_path:
        logger.error("ffmpeg not found. Install ffmpeg from an official distribution channel or set FFMPEG_PATH.")
        return False
    result = subprocess.run(
        [
            ffmpeg_path,
            "-loglevel",
            "quiet",
            "-y",
            "-f",
            "s16le",
            "-i",
            pcm_path,
            "-ar",
            "44100",
            "-ac",
            "1",
            mp3_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.returncode == 0


class MediaDB(DataBaseBase):
    def get_media_buffer(self, server_id) -> bytes:
        sql = '''
        select voice_data
        from VoiceInfo
        where svr_id = ?
        '''
        if not self.DB:
            return b''
        for db in self.DB:
            cursor = db.cursor()
            cursor.execute(sql, [server_id])
            result = cursor.fetchone()
            if result:
                return result[0]
        return b''

    def get_audio_path(self, server_id, output_dir, filename=''):
        if filename:
            return f'{output_dir}/{filename}.mp3'
        else:
            return f'{output_dir}/{server_id}.mp3'

    def get_audio(self, server_id, output_dir, filename=''):
        if not filename:
            filename = server_id
        silk_path = f"{output_dir}/{filename}.silk"
        pcm_path = f"{output_dir}/{filename}.pcm"
        mp3_path = f"{output_dir}/{filename}.mp3"
        if os.path.exists(mp3_path):
            return mp3_path
        buf = self.get_media_buffer(server_id)
        if not buf:
            return ''
        with open(silk_path, "wb") as f:
            f.write(buf)
        # open(silk_path, "wb").write()
        try:
            decode(silk_path, pcm_path, 44100)
            convert_pcm_to_mp3(pcm_path, mp3_path)
            if os.path.exists(silk_path):
                os.remove(silk_path)
            if os.path.exists(pcm_path):
                os.remove(pcm_path)
        except Exception as e:
            print(f"Error: {e}")
            logger.error(f'语音错误\n{traceback.format_exc()}')
            convert_pcm_to_mp3(pcm_path, mp3_path)
        finally:
            return mp3_path

    def merge(self, db_path):
        # todo 判断数据库对应情况
        if not (os.path.exists(db_path) or os.path.isfile(db_path)):
            print(f'{db_path} does not exist')
            return
        if not self.DB:
            shutil.copy(db_path,os.path.join(self.db_dir,self.db_file_name))
        else:
            for db in self.DB:
                cursor = db.cursor()
                try:
                    # 获取列名
                    increase_data(db_path, cursor, db, 'VoiceInfo', 'svr_id')
                    increase_data(db_path, cursor, db, 'Name2Id', 'user_name')
                    increase_update_data(db_path, cursor, db, 'Timestamp', 'timestamp')
                except:
                    print(f"数据库操作错误: {traceback.format_exc()}")
                    db.rollback()


if __name__ == '__main__':
    pass
