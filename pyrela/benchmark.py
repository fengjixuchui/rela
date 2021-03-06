# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved

import os
import sys
import pprint
import argparse
import time
from datetime import datetime
from tabulate import tabulate
import numpy as np

from create_atari import *
from utils import *
from net import AtariFFNet
from apex import ApexAgent
import common_utils


def benchmark_fps(args):
    pprint.pprint(vars(args))

    net_cons = lambda: AtariFFNet(args.num_action)
    agents = []
    lockers = []

    for i in range(args.num_gpu):
        agent = ApexAgent(net_cons, 3, 0.99).to("cuda:%d" % i)
        locker = rela.ModelLocker([agent], "cuda:%d" % i)
        agents.append(agent)
        lockers.append(locker)

    replay_buffer = rela.FFPrioritizedReplay(
        args.replay_buffer_size,
        args.seed,
        0.6,  # priority exponent
        0.4,  # importance sampling
        False,
    )

    eps = generate_eps(0.4, 7, args.num_thread * args.num_game_per_thread)
    actor_creator = lambda i: rela.DQNActor(
        lockers[i % args.num_gpu], 1, args.num_game_per_thread, 0.99, replay_buffer
    )

    context, games, actors = create_train_env(
        args.game,
        args.seed,
        eps,
        108000,  # args.max_frame
        args.num_thread,
        args.num_game_per_thread,
        actor_creator,
    )

    frame_stat = dict()
    frame_stat["num_acts"] = 0
    frame_stat["num_buffer"] = 0
    context.start()
    act_rates = []
    buffer_rates = []
    print("Beginning!")
    while replay_buffer.size() < args.burn_in_frames:
        print(
            "warming up replay buffer: %d/%d"
            % (replay_buffer.size(), args.burn_in_frames)
        )
        time.sleep(1)

    no_sample_rate = []
    sample_rate = []
    epoch_sec = 30
    num_epoch = 6
    for epoch in range(num_epoch):
        now = datetime.now()
        time.sleep(epoch_sec)
        secs = (datetime.now() - now).total_seconds()
        act_rate, _ = get_frame_stat(
            args.num_game_per_thread,
            secs,
            get_num_acts(actors),
            replay_buffer.num_add(),
            frame_stat,
        )
        no_sample_rate.append(act_rate)
        print(
            "without sample: epoch :%d, act rate: %d, buffer size: %d"
            % (epoch, act_rate, replay_buffer.size())
        )

    for epoch in range(num_epoch):
        now = datetime.now()
        batchsize = 512
        while (datetime.now() - now).total_seconds() <= epoch_sec:
            batch, weight = replay_buffer.sample(batchsize)
            replay_buffer.update_priority(weight)

        secs = (datetime.now() - now).total_seconds()
        act_rate, _ = get_frame_stat(
            args.num_game_per_thread,
            secs,
            get_num_acts(actors),
            replay_buffer.num_add(),
            frame_stat,
        )
        sample_rate.append(act_rate)
        print(
            "with sample: epoch :%d, act rate: %d, buffer size: %d"
            % (epoch, act_rate, replay_buffer.size())
        )

    context.terminate()

    sleeped = 0
    while not context.terminated():
        time.sleep(1)
        sleeped += 1
        print("Waited for %d sec for context to terminate" % sleeped)

    without_sample = np.mean(no_sample_rate[-num_epoch // 2 :])
    with_sample = np.mean(sample_rate[-num_epoch // 2 :])
    print(
        "act rate: without sample: %.2f, with sample: %.2f"
        % (without_sample, with_sample)
    )
    print("Finished!")
    return without_sample, with_sample


def benchmark(thread_game_worker, args):
    # thread_game_worker = [(4, 200)]
    summaries = []
    headers = [
        "#thread",
        "#game/therad",
        "act rate (w/o sample)",
        "act rate (with sample)",
    ]

    for num_thread, num_game_per_thread in thread_game_worker:
        print(
            "NUM_GPU: %d, trying %s x %s"
            % (args.num_gpu, num_thread, num_game_per_thread)
        )
        args.num_thread = num_thread
        args.num_game_per_thread = num_game_per_thread
        no_sample_rate, sample_rate = benchmark_fps(args)

        summaries.append([num_thread, num_game_per_thread, no_sample_rate, sample_rate])

    print("NUM_GPU:", args.num_gpu)
    print(tabulate(summaries, headers=headers))


def parse_args():
    parser = argparse.ArgumentParser(description="Run DQN on Atari")
    parser.add_argument("--save_dir", default="exps/benchmark", type=str)
    parser.add_argument("--game", default="boxing", help="game name")
    parser.add_argument("--seed", default=10001, type=int, help="Random seed")

    parser.add_argument("--num_gpu", default=1, type=int)
    parser.add_argument("--replay_buffer_size", default=2 ** 21, type=int)
    parser.add_argument("--burn_in_frames", default=1000, type=int)

    args = parser.parse_args()
    args.num_action = get_num_action(args.game)
    return args


if __name__ == "__main__":
    torch.backends.cudnn.benchmark = True

    args = parse_args()
    sys.stdout = common_utils.Logger(os.path.join(args.save_dir, "benchmark.log"))
    sys.stderr = common_utils.Logger(os.path.join(args.save_dir, "benchmark.err"))

    # thread_game_worker = [(10, 10)]
    # for num_gpu in [1, 2, 3, 4, 5, 6]:
    thread_game_worker = [
        (80, 20),
        (80, 40),
        (80, 80),
        (80, 160),
        # (120, 20), (120, 40), (120, 80), (120, 160),
        # (160, 20), (160, 40), (160, 80), (160, 160),
    ]
    # args.num_gpu = num_gpu
    benchmark(thread_game_worker, args)

    # thread_game_worker = [(80, 20), (80, 40), (80, 60)]
    # args.num_gpu = 2
    # benchmark(thread_game_worker, args)
