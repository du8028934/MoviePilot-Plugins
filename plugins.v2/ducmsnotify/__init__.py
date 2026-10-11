import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlsplit, urlunsplit

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel

from app.core.config import settings
from app.core.event import eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import Response
from app.schemas.types import EventType
from app.utils.http import RequestUtils


class CMSTestRequest(BaseModel):
    """配置页测试连接时提交的 CMS 参数。"""

    cms_domain: Optional[str] = ""
    cms_api_token: Optional[str] = ""
    cms_notify_type: Optional[str] = "lift_sync"


class DuCMSNotify(_PluginBase):
    # 插件名称
    plugin_name = "CMS通知测试"
    # 插件描述
    plugin_desc = "整理完成115里的媒体后，通知CMS进行增量同步（strm生成）"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/imaliang/MoviePilot-Plugins/main/icons/cms.png"
    # 插件版本
    plugin_version = "0.6"
    # 插件作者
    plugin_author = "du8028934"
    # 作者主页
    author_url = "https://github.com/imaliang"
    # 插件配置项ID前缀
    plugin_config_prefix = "ducmsnotify_"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _cms_notify_type = None
    _cms_domain = None
    _cms_api_token = None
    _enabled = False
    _last_event_time = 0
    # 等待通知数量
    _wait_notify_count = 0

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._cms_notify_type = config.get("cms_notify_type")
            self._cms_domain = config.get("cms_domain")
            self._cms_api_token = config.get('cms_api_token')

    def get_state(self) -> bool:
        return self._enabled

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self._enabled:
            return [{
                "id": "DuCMSNotify",
                "name": "CMS通知测试",
                "trigger": CronTrigger.from_crontab("* * * * *"),
                "func": self.__notify_cms,
                "kwargs": {}
            }]
        return []

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        注册配置页测试接口。
        """
        return [{
            "path": "/test",
            "endpoint": self.test_connection,
            "methods": ["POST"],
            "auth": "bear",
            "summary": "测试CMS连接",
            "description": "使用当前填写的地址和Token请求CMS",
        }]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'cms_notify_type',
                                            'label': '通知类型',
                                            'items': [
                                                {'title': '增量同步',
                                                    'value': 'lift_sync'},
                                                {'title': '增量同步+自动整理',
                                                    'value': 'auto_organize'},
                                            ]
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cms_domain',
                                            'label': 'CMS地址'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cms_api_token',
                                            'label': 'CMS_API_TOKEN'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VBtn',
                                        'text': '测试连接',
                                        'props': {
                                            'color': 'primary',
                                            'variant': 'tonal',
                                            'prepend-icon': 'mdi-connection',
                                            'loading': '{{ testing }}',
                                            'disabled': '{{ testing }}',
                                            'onclick': """async function() {
                                                if (!cms_domain || !cms_api_token) {
                                                    model.test_success = false
                                                    model.test_message = '请先填写 CMS 地址和 Token'
                                                    return
                                                }
                                                model.testing = true
                                                model.test_message = ''
                                                try {
                                                    const res = await window.MoviePilotAPI.post('plugin/DuCMSNotify/test', {
                                                        cms_domain: cms_domain,
                                                        cms_api_token: cms_api_token,
                                                        cms_notify_type: cms_notify_type || 'lift_sync'
                                                    })
                                                    model.test_success = !!(res && res.success)
                                                    model.test_message = (res && (res.message_i18n || res.message)) || (model.test_success ? '连接成功' : '连接失败')
                                                } catch (error) {
                                                    model.test_success = false
                                                    const detail = error && error.response && error.response.data
                                                    model.test_message = (detail && (detail.message_i18n || detail.message || detail.detail)) || (error && error.message) || '测试请求失败'
                                                } finally {
                                                    model.testing = false
                                                }
                                            }"""
                                        }
                                    },
                                    {
                                        'component': 'div',
                                        'props': {
                                            'class': 'text-caption text-medium-emphasis mt-2'
                                        },
                                        'text': '使用输入框里的地址和 Token，按当前通知类型向 CMS 发一次真实请求。'
                                    },
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': '{{ test_success ? "success" : "error" }}',
                                            'variant': 'tonal',
                                            'density': 'compact',
                                            'class': 'mt-3',
                                            'show': 'test_message',
                                            'text': '{{ test_message }}'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '当MP整理或刮削好115里的媒体后，会通知CMS进行增量同步（strm生成）；CMS版本需要0.3.5.11及以上：https://wiki.cmscc.cc'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '为了防止通知次数过于频繁，会有1-2分钟的等待，只有在此期间再无其它整理或刮削时，才会进行通知'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "cms_notify_type": "lift_sync",
            "cms_api_token": "cloud_media_sync",
            "cms_domain": "http://172.17.0.1:9527",
            "testing": False,
            "test_success": False,
            "test_message": ""
        }

    def get_page(self) -> List[dict]:
        pass

    @eventmanager.register(EventType)
    def monitor(self, event):
        """
        监听事件
        """
        if not self._enabled or not self._cms_domain or not self._cms_api_token:
            return

        if not event or not event.event_type:
            return

        def __to_dict(_event):
            """
            递归将对象转换为字典
            """
            if isinstance(_event, dict):
                for k, v in _event.items():
                    _event[k] = __to_dict(v)
                return _event
            elif isinstance(_event, list):
                for i in range(len(_event)):
                    _event[i] = __to_dict(_event[i])
                return _event
            elif isinstance(_event, tuple):
                return tuple(__to_dict(list(_event)))
            elif isinstance(_event, set):
                return set(__to_dict(list(_event)))
            elif hasattr(_event, 'to_dict'):
                return __to_dict(_event.to_dict())
            elif hasattr(_event, '__dict__'):
                return __to_dict(_event.__dict__)
            elif isinstance(_event, (int, float, str, bool, type(None))):
                return _event
            else:
                return str(_event)

        version = getattr(settings, "VERSION_FLAG", "v1")
        event_type = event.event_type if version == "v1" else event.event_type.value
        logger.debug(f"event_type: {event_type}")
        logger.debug(f"event_data: {event.event_data}")
        if event_type not in ["transfer.complete", "metadata.scrape"]:
            return
        event_data = __to_dict(event.event_data)

        logger.debug(f"event_data: {event_data}")
        if event_type == "transfer.complete":
            transferinfo = event_data["transferinfo"]
            success = transferinfo["success"]
            if success:
                storage = transferinfo["target_diritem"]["storage"]
                name = transferinfo["target_item"]["name"]
                if storage in ("u115", "115网盘Plus", 'CloudDrive储存'):
                    logger.info(f"115整理完成：{name}")
                    self._wait_notify_count += 1
                    self._last_event_time = self.__get_time()
        elif event_type == "metadata.scrape":
            storage = event_data["fileitem"]
            name = event_data["name"]
            if storage in ("u115", "115网盘Plus", 'CloudDrive储存'):
                self._wait_notify_count += 1
                self._last_event_time = self.__get_time()
                logger.info(f"115刮削完成：{name}")

    def __get_time(self):
        return int(time.time())

    @staticmethod
    def __build_cms_url(domain: Optional[str], token: Optional[str], notify_type: Optional[str]) -> Optional[str]:
        """
        生成 CMS 增量同步地址，Token 放在查询参数中。
        """
        domain = (domain or "").strip().rstrip("/")
        token = (token or "").strip()
        notify_type = (notify_type or "lift_sync").strip() or "lift_sync"
        parts = urlsplit(domain)
        if not token or parts.scheme not in {"http", "https"} or not parts.netloc:
            return None
        return urlunsplit((
            parts.scheme,
            parts.netloc,
            f"{parts.path}/api/sync/lift_by_token".replace("//", "/"),
            urlencode({"token": token, "type": notify_type}),
            "",
        ))

    def test_connection(self, body: CMSTestRequest) -> Response:
        """
        按当前填写的地址、Token 和通知类型请求 CMS。
        """
        domain = (body.cms_domain or "").strip().rstrip("/")
        token = (body.cms_api_token or "").strip()
        notify_type = (body.cms_notify_type or "lift_sync").strip() or "lift_sync"
        if not domain or not token:
            return Response(success=False, message="请先填写 CMS 地址和 Token")
        parts = urlsplit(domain)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            return Response(success=False, message="CMS 地址需要以 http:// 或 https:// 开头")
        if notify_type not in {"lift_sync", "auto_organize"}:
            return Response(success=False, message="通知类型不正确")

        url = self.__build_cms_url(domain=domain, token=token, notify_type=notify_type)
        try:
            ret = RequestUtils(timeout=15).get_res(url)
        except Exception as err:
            logger.error(f"测试CMS连接异常：{domain} - {err}")
            return Response(success=False, message=f"连接 CMS 失败：{err}")
        if ret is None:
            return Response(success=False, message="连接 CMS 失败，未获取到返回信息")

        payload = None
        try:
            payload = ret.json()
        except Exception:
            payload = None
        message = ""
        code = None
        if isinstance(payload, dict):
            code = payload.get("code")
            message = str(payload.get("msg") or payload.get("message") or "").strip()
        if not message:
            message = (ret.text or "").strip()[:200]
        if ret.status_code >= 400 or code not in (200, "200"):
            detail = message or ret.reason or "未知错误"
            logger.error(f"测试CMS连接失败：{domain} - {ret.status_code} {detail}")
            return Response(success=False, message=f"CMS 返回失败：{detail}")
        logger.info(f"测试CMS连接成功：{domain}")
        return Response(success=True, message=f"连接成功：{message or 'CMS 已接受请求'}")

    def __notify_cms(self):
        try:
            # 当等待通知数量超过1000或者有等待通知且最后事件时间超过60秒时触发通知
            if self._wait_notify_count > 0 and (self._wait_notify_count > 1000 or self.__get_time() - self._last_event_time > 60):
                url = self.__build_cms_url(
                    domain=self._cms_domain,
                    token=self._cms_api_token,
                    notify_type=self._cms_notify_type,
                )
                if not url:
                    logger.error("CMS地址或Token无效，无法通知")
                    return
                ret = RequestUtils().get_res(url)
                if ret:
                    logger.info("通知CMS执行增量同步成功")
                    self._wait_notify_count = 0
                elif ret is not None:
                    logger.error(
                        f"通知CMS失败，状态码：{ret.status_code}，返回信息：{ret.text} {ret.reason}")
                else:
                    logger.error("通知CMS失败，未获取到返回信息")
            else:
                if self._wait_notify_count > 0:
                    logger.info(
                        f"等待通知数量：{self._wait_notify_count}，最后事件时间：{self._last_event_time}")
        except Exception as e:
            logger.error(f"通知CMS发生异常：{e}")

    def stop_service(self):
        """
        退出插件
        """
        pass
