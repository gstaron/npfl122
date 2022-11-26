#!/usr/bin/env python3
import os
import sys

import gym
import numpy as np


############################
# Gym Environment Wrappers #
############################

class EvaluationEnv(gym.Wrapper):
    def __init__(self, env, seed=None, render_each=0, evaluate_for=100, report_each=10):
        super().__init__(env)
        self._render_each = render_each
        self._evaluate_for = evaluate_for
        self._report_each = report_each
        self._report_verbose = os.getenv("VERBOSE") not in [None, "", "0"]

        gym.Env.reset(self.unwrapped, seed=seed)
        self.action_space.seed(seed)
        self.observation_space.seed(seed)

        self._episode_running = False
        self._episode_returns = []
        self._evaluating_from = None
        self._original_render_mode = env.render_mode
        self._pygame = __import__("pygame") if self._render_each else None

    @property
    def episode(self):
        return len(self._episode_returns)

    def reset(self, *, start_evaluation=False, logging=True, seed=None, options=None):
        if seed is not None:
            raise RuntimeError("The EvaluationEnv cannot be reseeded")
        if self._evaluating_from is not None and self._episode_running:
            raise RuntimeError("Cannot reset a running episode after `start_evaluation=True`")
        if start_evaluation and self._evaluating_from is None:
            self._evaluating_from = self.episode

        if logging and self._render_each and (self.episode + 1) % self._render_each == 0:
            self.unwrapped.render_mode = "human"
        elif self._render_each:
            self.unwrapped.render_mode = self._original_render_mode
        self._episode_running = True
        self._episode_return = 0 if logging or self._evaluating_from is not None else None
        return super().reset(options=options)

    def step(self, action):
        if not self._episode_running:
            raise RuntimeError("Cannot run `step` on environments without an active episode, run `reset` first")

        observation, reward, terminated, truncated, info = super().step(action)
        done = terminated or truncated

        self._episode_running = not done
        if self._episode_return is not None:
            self._episode_return += reward
        if self._episode_return is not None and done:
            self._episode_returns.append(self._episode_return)

            if self._report_each and self.episode % self._report_each == 0:
                print("Episode {}, mean {}-episode return {:.2f} +-{:.2f}{}".format(
                    self.episode, self._evaluate_for, np.mean(self._episode_returns[-self._evaluate_for:]),
                    np.std(self._episode_returns[-self._evaluate_for:]), "" if not self._report_verbose else
                    ", returns " + " ".join(map("{:g}".format, self._episode_returns[-self._report_each:]))),
                    file=sys.stderr, flush=True)
            if self._evaluating_from is not None and self.episode >= self._evaluating_from + self._evaluate_for:
                print("The mean {}-episode return after evaluation {:.2f} +-{:.2f}".format(
                    self._evaluate_for, np.mean(self._episode_returns[-self._evaluate_for:]),
                    np.std(self._episode_returns[-self._evaluate_for:])), flush=True)
                self.close()
                sys.exit(0)

        if self._pygame and self.unwrapped.render_mode == "human" and self._pygame.get_init():
            if self._pygame.event.get(self._pygame.QUIT):
                self.unwrapped.render_mode = self._original_render_mode

        return observation, reward, terminated, truncated, info


class DiscretizationWrapper(gym.ObservationWrapper):
    def __init__(self, env, separators, tiles=None):
        super().__init__(env)
        self._separators = separators
        self._tiles = tiles

        if tiles is None:
            states = 1
            for separator in separators:
                states *= 1 + len(separator)
            self.observation_space = gym.spaces.Discrete(states)
        else:
            self._first_tile_states, self._rest_tiles_states = 1, 1
            for separator in separators:
                self._first_tile_states *= 1 + len(separator)
                self._rest_tiles_states *= 2 + len(separator)
            self.observation_space = gym.spaces.MultiDiscrete([
                self._first_tile_states + i * self._rest_tiles_states for i in range(tiles)])

            self._separator_offsets = [0 if len(s) <= 1 else (s[1] - s[0]) / tiles for s in separators]
            self._separator_tops = [np.inf if len(s) <= 1 else s[-1] + (s[1] - s[0]) for s in separators]

    def observation(self, observations):
        state = 0
        for observation, separator in zip(observations, self._separators):
            state *= 1 + len(separator)
            state += np.digitize(observation, separator)
        if self._tiles is None:
            return state
        else:
            states = np.empty(self._tiles, dtype=np.int64)
            states[0] = state
            for t in range(1, self._tiles):
                state = 0
                for i in range(len(self._separators)):
                    state *= 2 + len(self._separators[i])
                    value = observations[i] + ((t * (2 * i + 1)) % self._tiles) * self._separator_offsets[i]
                    if value > self._separator_tops[i]:
                        state += 1 + len(self._separators[i])
                    else:
                        state += np.digitize(value, self._separators[i])
                states[t] = self._first_tile_states + (t - 1) * self._rest_tiles_states + state
            return states


class DiscreteCartPoleWrapper(DiscretizationWrapper):
    def __init__(self, env, bins=8):
        super().__init__(env, [
            np.linspace(-2.4, 2.4, num=bins + 1)[1:-1],  # cart position
            np.linspace(-3, 3, num=bins + 1)[1:-1],      # cart velocity
            np.linspace(-0.2, 0.2, num=bins + 1)[1:-1],  # pole angle
            np.linspace(-2, 2, num=bins + 1)[1:-1],      # pole angle velocity
        ])


class DiscreteMountainCarWrapper(DiscretizationWrapper):
    def __init__(self, env, bins=None, tiles=None):
        if bins is None:
            bins = 24 if tiles is None or tiles <= 1 else 12 if tiles <= 3 else 8
        super().__init__(env, [
            np.linspace(-1.2, 0.6, num=bins + 1)[1:-1],    # car position
            np.linspace(-0.07, 0.07, num=bins + 1)[1:-1],  # car velocity
        ], tiles)


class DiscreteLunarLanderWrapper(DiscretizationWrapper):
    def __init__(self, env):
        super().__init__(env, [
            np.linspace(-.4, .4, num=5 + 1)[1:-1],      # position x
            np.linspace(-.075, 1.35, num=6 + 1)[1:-1],  # position y
            np.linspace(-.5, .5, num=5 + 1)[1:-1],      # velocity x
            np.linspace(-.8, .8, num=7 + 1)[1:-1],      # velocity y
            np.linspace(-.2, .2, num=3 + 1)[1:-1],      # rotation
            np.linspace(-.2, .2, num=5 + 1)[1:-1],      # ang velocity
            [.5],                                       # left contact
            [.5],                                       # right contact
        ])

        self._expert = gym.make("LunarLander-v2")
        gym.Env.reset(self._expert.unwrapped, seed=42)

    def expert_trajectory(self, seed=None):
        state, trajectory, done = self._expert.reset(seed=None)[0], [], False
        while not done:
            action = gym.envs.box2d.lunar_lander.heuristic(self._expert, state)
            next_state, reward, terminated, truncated, _ = self._expert.step(action)
            trajectory.append((self.observation(state), action, reward))
            done = terminated or truncated
            state = next_state
        trajectory.append((self.observation(state), None, None))
        return trajectory


####################
# Gym Environments #
####################

gym.envs.register(
    id="MountainCar1000-v0",
    entry_point="gym.envs.classic_control:MountainCarEnv",
    max_episode_steps=1000,
    reward_threshold=-110.0,
)


#############
# Utilities #
#############

def typed_np_function(*types):
    """Typed NumPy function decorator.

    Can be used to wrap a function expecting NumPy inputs.

    It converts input positional arguments to NumPy arrays of the given types,
    and passes the result through `np.array` before returning (while keeping
    original tuples, lists and dictionaries).
    """
    def check_typed_np_function(wrapped, args):
        if len(types) != len(args):
            while hasattr(wrapped, "__wrapped__"):
                wrapped = wrapped.__wrapped__
            raise AssertionError("The typed_np_function decorator for {} expected {} arguments, but got {}".format(
                wrapped, len(types), len(args)))

    def structural_map(function, value):
        if isinstance(value, tuple):
            return tuple(structural_map(function, element) for element in value)
        if isinstance(value, list):
            return [structural_map(function, element) for element in value]
        if isinstance(value, dict):
            return {key: structural_map(function, element) for key, element in value.items()}
        return function(value)

    class TypedNpFunctionWrapper:
        def __init__(self, func):
            self.__wrapped__ = func

        def __call__(self, *args, **kwargs):
            check_typed_np_function(self.__wrapped__, args)
            return structural_map(np.array, self.__wrapped__(
                *[np.asarray(arg, typ) for arg, typ in zip(args, types)], **kwargs))

        def __get__(self, instance, cls):
            return TypedNpFunctionWrapper(self.__wrapped__.__get__(instance, cls))

    return TypedNpFunctionWrapper


def raw_tf_function(dynamic_dims):
    """Faster but raw `tf.function` implementation.

    All unnecessary steps are shaven off, only the Graph execution is performed.
    Only positional Numpy arguments are supported, the result is either a Numpy
    array or a list of them. Uses TensorFlow internals, so it might not work for you.

    The `dynamic_dims` argument specified the number of "dynamic" (not known statically
    in the computational graph) dimensions of every input. It can be either
    - an integer, in which case it is used for all inputs, or
    - a list, whose elements correspond to the positional arguments of the TF call.
    """
    import weakref

    import tensorflow as tf
    import tensorflow.python.eager as tfe
    import tensorflow.python.framework.constant_op as constant_op

    class RawTFFunctionWrapper:
        def __init__(self, func):
            self.__wrapped__ = func
            self._concrete_function = None
            self._instances = weakref.WeakKeyDictionary()

        def __call__(self, *args):
            if self._concrete_function is None:
                self._concrete_function = tf.function(self.__wrapped__).get_concrete_function(
                    *[tf.TensorSpec((None,) * dynamic + arg.shape[1:], dtype=tf.dtypes.as_dtype(arg.dtype))
                      for arg, dynamic in zip(
                          args, dynamic_dims if isinstance(dynamic_dims, list) else [dynamic_dims] * len(args))])
            ctx = tfe.context.context()
            inputs = [constant_op.convert_to_eager_tensor(np.asarray(arg), ctx) for arg in args]
            result = tfe.execute.execute(self._concrete_function.name, len(self._concrete_function.outputs),
                                         inputs + self._concrete_function.captured_inputs, {}, ctx)
            return result[0] if len(self._concrete_function.outputs) == 1 else result

        def __get__(self, instance, cls):
            wrapper = self._instances.get(instance, None)
            if wrapper is None:
                self._instances[instance] = wrapper = RawTFFunctionWrapper(self.__wrapped__.__get__(instance, cls))
            return wrapper

    return RawTFFunctionWrapper
