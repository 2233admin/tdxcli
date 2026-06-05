# 通达信量化平台 (TdxQuant)

Use when the user needs to work with 通达信量化平台 (TdxQuant), including writing Python strategies, getting market data, backtesting, or trading via the TdxQuant API.

> 完整文档位于 `C:/temp/tdx-dev-docs/`

## TdxQuant API

### 安装 Python 环境
```bash
pip install pandas numpy pytdx mootdx
```

### 基本使用
```python
from tqcenter import tq

# 初始化 (所有策略都必须调用)
tq.initialize(__file__)

# 获取日线前复权收盘数据
df = tq.get_market_data(
    field_list=['Close'],
    stock_list=["000001.SZ"],
    start_time='20251219',
    end_time='20251225',
    dividend_type='front',
    period='1d',
)
print(df)
```

### 目录结构
```
通达信安装目录/
├── PYPlugins/user/           # 策略代码目录
│   ├── tqcenter.py          # TQ核心支撑文件 (勿修改!)
│   └── *.py                  # 你的策略文件
└── T0002/hq_cache/          # K线数据缓存
```

## 行情数据获取

### 通用函数

| 函数 | 说明 |
|------|------|
| `tq.get_market_data()` | 获取行情数据 |
| `tq.get_stock_list_in_sector()` | 获取板块成分股 |
| `tq.get_history_instrument_data()` | 获取历史合约信息 |

### 数据字段

| 字段 | 说明 |
|------|------|
| Open | 开盘价 |
| High | 最高价 |
| Low | 最低价 |
| Close | 收盘价 |
| Volume | 成交量 |
| Amount | 成交额 |

### 时间周期

| period | 说明 |
|--------|------|
| 1d | 日线 |
| 1m/5m/15m/30m/60m | 分钟线 |

### 复权类型

| dividend_type | 说明 |
|--------------|------|
| none | 不复权 |
| front | 前复权 |
| back | 后复权 |

## 板块操作

```python
# 获取板块成分股
stocks = tq.get_stock_list_in_sector('通达信88')
```

## 选股示例

```python
import pandas as pd
from tqcenter import tq

tq.initialize(__file__)
stocks = tq.get_stock_list_in_sector('通达信88')

df = tq.get_market_data(
    field_list=['Close', 'Open'],
    stock_list=stocks,
    period='1d',
)

# 选股条件: 涨幅超过5%
result = df[df['Close'] > df['Open'] * 1.05]
```

## 量化交易流程

1. **投资想法** → 形成交易策略
2. **策略细化** → 确定品种、条件、数量
3. **代码实现** → 编写Python策略
4. **回测验证** → 历史数据测试
5. **实盘运行** → 实时交易

## 交易函数

```python
tq.buy(stock_code, price, quantity)    # 买入
tq.sell(stock_code, price, quantity) # 卖出
tq.get_positions()                    # 查询持仓
tq.get_account()                     # 查询账户
```

## 完整文档索引

| 类别 | 位置 |
|------|------|
| 快速开始 | `01-quick-start/` |
| API 参考 | `02-api-reference/` |
| 用户手册 | `03-user-manuals/` |
| 公式系统 | `04-formulas/` |
