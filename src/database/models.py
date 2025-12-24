import uuid
from enum import Enum as PyEnum

from sqlalchemy import (BigInteger, Boolean, Column, Enum, ForeignKey, Integer,
                        String, Text, TypeDecorator, UniqueConstraint)
from sqlalchemy.dialects.sqlite import BLOB, JSON
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import declarative_base, relationship


class LowercaseString(TypeDecorator):
    """Ensures that all strings stored in this column are lowercase."""

    impl = String

    def process_bind_param(self, value, dialect):
        if value is not None:
            return value.lower()
        return value

    def process_result_value(self, value, dialect):
        return value


Base = declarative_base()


def gen_uuid() -> bytes:
    """Generate a UUID4 in bytes format for use as primary key."""
    return uuid.uuid4().bytes


# Transaction type enum, stored as int
class TransactionType(PyEnum):
    INCOME = 1  # both income and spend
    # TRANSFER = 2  # transfer from one wallet to another


class User(Base):
    __tablename__ = "users"

    id = Column(BLOB, primary_key=True, default=gen_uuid)
    telegram_id = Column(Integer, unique=True, nullable=False)
    registered_at = Column(BigInteger, nullable=False)  # unix timestamp
    language = Column(String, nullable=True)
    is_banned = Column(Boolean, default=False)
    expectation = Column(MutableDict.as_mutable(JSON), nullable=True)

    wallets = relationship("Wallet", back_populates="holder_user")
    categories = relationship("Category", back_populates="holder_user")
    transactions = relationship("Transaction", back_populates="holder_user")


class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(BLOB, primary_key=True, default=gen_uuid)
    holder = Column(BLOB, ForeignKey("users.id"), nullable=False)
    created_at = Column(BigInteger, nullable=False)  # unix timestamp
    icon = Column(String(1), nullable=False)
    name = Column(LowercaseString, nullable=False)
    currency = Column(String(8), nullable=False)  # like "USD" or "UAH"
    init_sum = Column(BigInteger, nullable=False, default=0)
    current_sum = Column(BigInteger, nullable=False, default=0)
    transaction_count = Column(BigInteger, nullable=False, default=0)
    is_deleted = Column(Boolean, default=False)
    comment = Column(Text, nullable=True)

    holder_user = relationship("User", back_populates="wallets")
    transactions = relationship("Transaction", back_populates="wallet")


class Category(Base):
    __tablename__ = "categories"

    id = Column(BLOB, primary_key=True, default=gen_uuid)
    holder = Column(BLOB, ForeignKey("users.id"), nullable=False)
    created_at = Column(BigInteger, nullable=False)  # unix timestamp
    icon = Column(String(1), nullable=False)
    name = Column(LowercaseString, nullable=False)
    transaction_count = Column(BigInteger, nullable=False, default=0)
    is_deleted = Column(Boolean, default=False)
    comment = Column(Text, nullable=True)

    holder_user = relationship("User", back_populates="categories")
    transactions = relationship("Transaction", back_populates="category")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(BLOB, primary_key=True, default=gen_uuid)
    holder = Column(BLOB, ForeignKey("users.id"), nullable=False)
    datetime = Column(BigInteger, nullable=False)  # unix timestamp in seconds
    type = Column(Enum(TransactionType), nullable=False)
    wallet_id = Column(BLOB, ForeignKey("wallets.id"), nullable=False)
    category_id = Column(BLOB, ForeignKey("categories.id"), nullable=False)
    sum = Column(BigInteger, nullable=False)
    comment = Column(Text, nullable=True)

    holder_user = relationship("User", back_populates="transactions")
    wallet = relationship("Wallet", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")


class WalletAlias(Base):
    __tablename__ = "wallet_aliases"

    id = Column(BLOB, primary_key=True, default=gen_uuid)
    holder = Column(BLOB, ForeignKey("users.id"), nullable=False)
    wallet = Column(BLOB, ForeignKey("wallets.id"), nullable=False)
    alias = Column(LowercaseString, nullable=False)

    holder_user = relationship("User", backref="wallet_aliases")
    wallet_ref = relationship("Wallet", backref="aliases")

    __table_args__ = (
        UniqueConstraint("holder", "alias", name="uq_wallet_alias_per_user"),
    )


class CategoryAlias(Base):
    __tablename__ = "category_aliases"

    id = Column(BLOB, primary_key=True, default=gen_uuid)
    holder = Column(BLOB, ForeignKey("users.id"), nullable=False)
    category = Column(BLOB, ForeignKey("categories.id"), nullable=False)
    alias = Column(LowercaseString, nullable=False)

    holder_user = relationship("User", backref="category_aliases")
    category_ref = relationship("Category", backref="aliases")

    __table_args__ = (
        UniqueConstraint("holder", "alias", name="uq_category_alias_per_user"),
    )
