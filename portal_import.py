"""Administrator-only import after independently verifying account ownership."""

import argparse

from portal_data import _account, _client, import_existing


def main():
    parser = argparse.ArgumentParser(description="核实账户归属后，从只读来源表复制本人已有资料到 AR 表")
    parser.add_argument("role", choices=["candidate", "alumni"])
    parser.add_argument("phone", help="已核实的注册手机号")
    args = parser.parse_args()
    client, app_token = _client()
    account = _account(client, app_token, args.role, args.phone)
    if not account:
        parser.error("该手机号尚未在对应用户端注册")
    print(import_existing({"id": account["record_id"], "role": args.role, "phone": args.phone})["message"])


if __name__ == "__main__":
    main()
