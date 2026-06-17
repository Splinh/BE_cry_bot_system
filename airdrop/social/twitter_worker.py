"""
Twitter (X) Worker - Dieu khien hang loat account Twitter de lam nhiem vu Galxe/Zealy.
- Ket noi bang API cua Twitter (Tweepy)
- Tu dong Like, Retweet, Quote Tweet, Follow
- Doi Proxy thay doi IP cho tung acc chong ban.
"""
import time
from loguru import logger
from typing import Optional

try:
    import tweepy
except ImportError:
    pass

class TwitterWorker:
    """
    Quan ly va dieu khien 1 tai khoan Twitter qua API.
    Can cung cap API Key, API Secret, Access Token, Access Secret.
    """
    
    def __init__(self, username: str, consumer_key: str, consumer_secret: str, 
                 access_token: str, access_token_secret: str, proxy: str = None):
        self.username = username
        self.proxy = proxy
        
        try:
            # Dung API v2 cua X/Twitter (tweepy.Client)
            self.client = tweepy.Client(
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                access_token=access_token,
                access_token_secret=access_token_secret,
                wait_on_rate_limit=True
            )
            
            # Dung API v1.1 cu cho mot so thao tac khong the thieu (Neu v2 ko co)
            auth = tweepy.OAuth1UserHandler(
                consumer_key, consumer_secret, access_token, access_token_secret
            )
            self.api = tweepy.API(auth, proxy=self.proxy)
            
            logger.info(f"Khoi tao Twitter Worker cho: @{self.username}")
        except Exception as e:
            logger.error(f"Loi khoi tao Twitter [{self.username}]: {e}")
            self.client = None
            self.api = None

    def test_connection(self) -> bool:
        """Kiem tra xem API keys co hoat dong khong."""
        if not self.client:
            return False
            
        try:
            me = self.client.get_me()
            logger.success(f"[{self.username}] Authenticated as @{me.data.username}")
            return True
        except Exception as e:
            logger.error(f"[{self.username}] Loi dang nhap: {e}")
            return False

    def like_tweet(self, tweet_id: str) -> bool:
        """Like 1 bai viet."""
        try:
            self.client.like(tweet_id)
            logger.success(f"[{self.username}] \u2764\ufe0f Liked tweet: {tweet_id}")
            return True
        except Exception as e:
            logger.warning(f"[{self.username}] Khong the like {tweet_id}: {e}")
            return False

    def retweet(self, tweet_id: str) -> bool:
        """Retweet (Share) 1 bai viet."""
        try:
            self.client.retweet(tweet_id)
            logger.success(f"[{self.username}] \U0001f504 Retweeted: {tweet_id}")
            return True
        except Exception as e:
            logger.warning(f"[{self.username}] Khong the retweet {tweet_id}: {e}")
            return False
            
    def follow_user(self, target_user_id: str) -> bool:
        """Theo doi 1 account (VD: project airdrop)."""
        try:
            self.client.follow_user(target_user_id)
            logger.success(f"[{self.username}] \U0001f465 Followed user ID: {target_user_id}")
            return True
        except Exception as e:
            logger.warning(f"[{self.username}] Loi follow {target_user_id}: {e}")
            return False

class TwitterManager:
    """Dieu khien nhieu Worker (Bot Net) chay cung 1 chien dich Airdrop."""
    
    def __init__(self):
        self.workers: dict[str, TwitterWorker] = {}
        
    def add_account(self, username: str, keys: dict, proxy: str = None):
        """Them 1 tai khoan vao quan lay."""
        worker = TwitterWorker(
            username=username,
            consumer_key=keys.get("consumer_key", ""),
            consumer_secret=keys.get("consumer_secret", ""),
            access_token=keys.get("access_token", ""),
            access_token_secret=keys.get("access_token_secret", ""),
            proxy=proxy
        )
        self.workers[username] = worker
        logger.info(f"Them Twitter Account Manager cho @{username}")

    def raid_tweet(self, tweet_id: str):
        """Dieu tat ca tai khoan dong loat Like + Retweet 1 bai dang."""
        logger.info(f"====== X-RAID KICH HOAT tren TWEET [{tweet_id}] nang {len(self.workers)} acc ======")
        for name, worker in self.workers.items():
            worker.like_tweet(tweet_id)
            time.sleep(2)  # Chong API Rate Limit
            worker.retweet(tweet_id)
            time.sleep(5)  # Nen doi 5-10 giay giua cac acc de tranh bi X quet bot net

    def mass_follow(self, target_user_id: str):
        """Dieu binh doan follow 1 project moi."""
        logger.info(f"====== MASS FOLLOW [{target_user_id}] ======")
        for name, worker in self.workers.items():
            worker.follow_user(target_user_id)
            time.sleep(10)  # Follow hang loat rat nguy hiem, phai doi lau
