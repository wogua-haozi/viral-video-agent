"""Create a pilot account locally; credentials are never command-line arguments."""

import argparse
import asyncio
from getpass import GetPassWarning, getpass
import warnings

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.api.schemas import UserCreate
from src.auth.security import hash_password
from src.db.session import async_session_factory, engine
from src.repositories import UserRepository


async def create_user(email: str, password: str) -> None:
    try:
        payload = UserCreate(email=email, password=password)
    except ValidationError:
        raise ValueError("邮箱格式不正确，或密码长度不在 8–128 位之间。") from None
    async with async_session_factory() as db:
        repo = UserRepository(db)
        if await repo.get_by_email(str(payload.email)):
            raise ValueError("该邮箱已存在，请使用已有账号。")
        try:
            await repo.create(str(payload.email), hash_password(payload.password))
        except IntegrityError:
            raise ValueError("该邮箱已存在，请使用已有账号。") from None


def main() -> None:
    parser = argparse.ArgumentParser(description="在已迁移的数据库中人工开通试用账号")
    parser.add_argument("email")
    args = parser.parse_args()

    async def provision():
        try:
            await create_user(args.email, password)
        finally:
            await engine.dispose()

    try:
        with warnings.catch_warnings():
            # getpass otherwise falls back to echoed stdin in a non-TTY.
            warnings.simplefilter("error", GetPassWarning)
            password = getpass("密码（不回显）: ")
            if password != getpass("再次输入密码: "):
                raise ValueError("两次密码不一致。")
        asyncio.run(provision())
    except GetPassWarning:
        parser.exit(1, "无法隐藏密码输入，请在交互终端中运行账号开通命令。\n")
    except (EOFError, KeyboardInterrupt):
        parser.exit(1, "已取消账号创建。\n")
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    except SQLAlchemyError:
        parser.exit(1, "无法写入账号，请核对数据库连接及迁移状态。\n")
    print("试用账号已创建。")


if __name__ == "__main__":
    main()
