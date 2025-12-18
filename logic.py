import random
from typing import List, Tuple


def build_secret_santa_pairs(user_ids: List[int]) -> dict[int, int]:
    """
    Классический тайный санта:
    каждый участник получает ровно одного подопечного,
    сам себе назначен быть не может.
    """
    if len(user_ids) < 2:
        raise ValueError("Нужно минимум 2 участника")

    shuffled = user_ids[:]
    random.shuffle(shuffled)

    return {
        shuffled[i]: shuffled[(i + 1) % len(shuffled)]
        for i in range(len(shuffled))
    }


def split_into_groups_max5(user_ids: List[int]) -> List[List[int]]:
    """
    Правила:
    - группы примерно равные
    - максимум 5 человек в группе
    - остаток 3–4 → отдельная группа
    - остаток 1–2 → докидываем в последнюю (получается 6–7)
    - если получилась одна большая группа (6–7) → делим на две
    """
    ids = user_ids[:]
    groups: List[List[int]] = []

    n = len(ids)
    if n == 0:
        return groups

    i = 0
    while n - i >= 5:
        groups.append(ids[i:i + 5])
        i += 5

    rem = ids[i:]
    if rem:
        if len(rem) in (3, 4):
            groups.append(rem)
        else:
            if not groups:
                groups.append(rem)
            else:
                groups[-1].extend(rem)

    # 🔧 ПАТЧ: не допускаем одну группу
    if len(groups) == 1 and len(groups[0]) > 3:
        g = groups.pop()
        mid = len(g) // 2
        groups.append(g[:mid])
        groups.append(g[mid:])

    return groups


def make_wave_mapping(active: List[int], passive: List[int]) -> List[Tuple[int, int]]:
    """
    Назначение целей в волне.

    Базовое правило:
    - каждый ACTIVE получает РОВНО ОДНУ цель

    Допустимое исключение:
    - если PASSIVE меньше, один PASSIVE может быть целью
      для двух ACTIVE (2к1)

    Запрещено:
    - один ACTIVE → две цели (1к2)
    """
    a = active[:]
    p = passive[:]

    random.shuffle(a)
    random.shuffle(p)

    pairs: List[Tuple[int, int]] = []

    # ✅ стандарт 1к1
    if len(a) <= len(p):
        for i, aid in enumerate(a):
            pairs.append((aid, p[i]))
        return pairs

    # ⚠️ исключение 2к1 (active больше)
    counts = {pid: 0 for pid in p}
    idx = 0

    for aid in a:
        tries = 0
        while tries < len(p) and counts[p[idx % len(p)]] >= 2:
            idx += 1
            tries += 1

        target = p[idx % len(p)]
        counts[target] += 1
        pairs.append((aid, target))
        idx += 1

    return pairs
